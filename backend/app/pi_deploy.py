"""Single-Pi SSH deployer. Network work never runs on the ASGI event loop.

Only the BoardVision user service is replaced. Closing the client does not
stop the remote program; the service is deliberately not enabled at boot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
import shlex
import threading
import time
from typing import Callable

import paramiko

from app.config import PiDeployConfig

SERVICE = "boardvision-pi.service"
LOG_BYTES = 128 * 1024


class RemoteCommandError(RuntimeError):
    pass


@dataclass
class PiStatus:
    host: str
    username: str
    remote_dir: str
    connected: bool = False
    hostname: str = ""
    python_version: str = ""
    busy: bool = False
    deployment: str = "idle"
    program: str = "unknown"
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None
    connection_error: str | None = None
    logs: list[str] = field(default_factory=list)


def program_status(properties: str) -> dict:
    props = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    active = props.get("ActiveState", "inactive")
    pid = int(props.get("MainPID", "0")) or None
    exited = props.get("ExecMainCode", "0") != "0"
    exit_code = int(props.get("ExecMainStatus", "0")) if exited else None
    if props.get("LoadState") == "not-found":
        program = "not_deployed"
    elif props.get("LoadState") in ("bad-setting", "error", "masked"):
        program = "failed"
    elif active == "failed":
        program = "failed"
    elif active in ("activating", "deactivating"):
        program = "starting" if active == "activating" else "stopping"
    elif active == "active" and pid:
        program = "running"
    else:
        program = "exited" if exited else "stopped"
    return {"program": program, "pid": pid, "exit_code": exit_code}


class PiDeployer:
    def __init__(self, config: PiDeployConfig, client_factory: Callable = paramiko.SSHClient):
        self.config = config
        self._factory = client_factory
        self._ssh = None
        self._home = ""
        self._state = PiStatus(config.host, config.username, config.remote_dir)
        self._state_lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._last_poll = 0.0
        self._worker: threading.Thread | None = None
        self._closed = False
        self._test_reserved: str | None = None

    def _set(self, **values):
        with self._state_lock:
            for key, value in values.items():
                setattr(self._state, key, value)

    def snapshot(self) -> dict:
        with self._state_lock:
            return {**asdict(self._state), "component_test_id": self._test_reserved}

    def _open(self):
        if self._closed:
            raise RuntimeError("Deployment client is shutting down")
        if self._ssh and self._ssh.get_transport() and self._ssh.get_transport().is_active():
            return
        self._disconnect()
        client = self._factory()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.config.host, port=self.config.port, username=self.config.username,
                password=self.config.password.get_secret_value(),
                allow_agent=False, look_for_keys=False,
                timeout=self.config.timeout_s, banner_timeout=self.config.timeout_s,
                auth_timeout=self.config.timeout_s, channel_timeout=self.config.timeout_s,
            )
            client.get_transport().set_keepalive(15)
            self._ssh = client
        except Exception:
            client.close()
            raise

    def _disconnect(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None

    def _sftp(self):
        sftp = self._ssh.open_sftp()
        sftp.get_channel().settimeout(self.config.timeout_s)
        return sftp

    def _run(self, command: str, timeout: float = 20) -> str:
        stdin, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
        stdin.close()
        channel = stdout.channel
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        try:
            while True:
                if channel.recv_ready():
                    out.extend(channel.recv(65536))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(65536))
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Pi command timed out")
                time.sleep(0.02)
            code = channel.recv_exit_status()
            output = out.decode("utf-8", errors="replace")
            if code != 0:
                detail = err.decode("utf-8", errors="replace").strip() or output.strip()
                raise RemoteCommandError(detail or f"Pi command exited with status {code}")
            return output.strip()
        finally:
            channel.close()

    def _failure(self, error: Exception, *, deployment: bool = False):
        if isinstance(error, RemoteCommandError):
            self._set(error=str(error), **({"deployment": "failed"} if deployment else {"program": "unknown", "pid": None}))
        else:
            self._disconnect()
            self._set(connected=False, program="unknown", pid=None, exit_code=None,
                      connection_error=str(error) or type(error).__name__,
                      **({"deployment": "failed"} if deployment else {}))

    def connect(self) -> dict:
        with self._state_lock:
            if self._state.busy or self._test_reserved:
                return {"ok": False, "error": "Pi operation already in progress", "status": self.snapshot()}
            self._state.busy = True
        failure = None
        try:
            with self._io_lock:
                try:
                    self._open()
                    hostname = self._run("hostname")
                    python_version = self._run("python3 --version")
                    with self._sftp() as sftp:
                        self._home = sftp.normalize(".")
                    self._set(connected=True, hostname=hostname, python_version=python_version,
                              connection_error=None, error=None)
                    self._refresh()
                except Exception as error:
                    self._failure(error)
                    failure = str(error)
        finally:
            self._set(busy=False)
        return {"ok": failure is None, "error": failure, "status": self.snapshot()}

    def deploy(self, code: str, *, imports=(), devices=()) -> dict:
        with self._state_lock:
            if self._closed or not self._state.connected:
                return {"ok": False, "error": "Connect to the Pi first", "status": self.snapshot()}
            if self._state.busy or self._test_reserved:
                return {"ok": False, "error": "Pi operation already in progress", "status": self.snapshot()}
            self._state.busy = True
            self._state.deployment = "preparing"
            self._state.error = None
            self._state.connection_error = None
            self._worker = threading.Thread(target=self._deploy, args=(code, tuple(imports), tuple(devices)), name="pi-deploy", daemon=True)
            self._worker.start()
        return {"ok": True, "status": self.snapshot()}

    def _write(self, path: str, contents: str):
        with self._sftp() as sftp:
            with sftp.file(path, "wb") as target:
                target.write(contents.encode("utf-8"))

    def _deploy(self, code: str, imports=(), devices=()):
        with self._io_lock:
            try:
                self._open()
                root = PurePosixPath(self.config.remote_dir)
                if not root.is_absolute() or root.name != "Pi_deployer":
                    raise RemoteCommandError("Deployment directory must be an absolute Pi_deployer path")
                pending, main = str(root / "main.pending.py"), str(root / "main.py")
                python = str(root / ".venv/bin/python")
                units = str(PurePosixPath(self._home) / ".config/systemd/user")
                self._run(f"mkdir -p {shlex.quote(str(root))} {shlex.quote(units)}")
                self._set(deployment="uploading")
                self._write(pending, code.replace("\r\n", "\n"))
                self._set(deployment="checking")
                # Check with the Pi's Python version before touching the running service.
                check = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_text(encoding='utf-8'), str(p), 'exec')"
                self._run(f"python3 -c {shlex.quote(check)} {shlex.quote(pending)}")
                self._run(f"test -x {shlex.quote(python)} || python3 -m venv --system-site-packages {shlex.quote(str(root / '.venv'))}", timeout=60)
                try:
                    self._run(f"{shlex.quote(python)} -c 'import gpiozero, lgpio'")
                except RemoteCommandError as error:
                    raise RemoteCommandError("Pi GPIO environment is not ready. On Raspberry Pi OS, prepare "
                        "python3-gpiozero and python3-lgpio, then recreate the --system-site-packages venv if needed. "
                        "No packages were installed automatically.\n" + str(error)) from error
                # Catalog-owned requirements, checked before stopping the old
                # service. Neither generated code nor the browser selects pip packages.
                extra = set(imports) - {"gpiozero", "lgpio"}
                if extra - {"spidev", "PIL", "luma.lcd"} or set(devices) - {"/dev/spidev0.0"}:
                    raise RemoteCommandError("Unknown catalog runtime requirement")
                if extra:
                    check = "import importlib; " + "; ".join(f"importlib.import_module({name!r})" for name in sorted(extra))
                    try:
                        self._run(f"{shlex.quote(python)} -c {shlex.quote(check)}")
                    except RemoteCommandError as error:
                        raise RemoteCommandError("ILI9341 environment is not ready. Install luma.lcd==2.13.0 in the deployment venv "
                            "and prepare python3-spidev / python3-pil. No packages were installed automatically.\n" + str(error)) from error
                for device in devices:
                    try:
                        self._run(f"test -r {shlex.quote(device)} && test -w {shlex.quote(device)}")
                    except RemoteCommandError as error:
                        raise RemoteCommandError("SPI0 is missing or inaccessible. Enable SPI in raspi-config, reboot if required, "
                            "and check that this user belongs to the spi group: " + device) from error
                unit = (
                    "[Unit]\nDescription=BoardVision Pi program\nStartLimitIntervalSec=0\n\n[Service]\nType=simple\n"
                    f'WorkingDirectory={root}\nExecStart="{python}" -u "{main}"\n'
                    "Environment=PYTHONUNBUFFERED=1\nEnvironment=GPIOZERO_PIN_FACTORY=lgpio\n"
                    "Restart=no\nKillMode=control-group\nTimeoutStopSec=5\n"
                    f"StandardOutput=append:{root}/run.log\nStandardError=append:{root}/run.log\n"
                    "\n[Install]\nWantedBy=default.target\n"
                )
                # Install (but never enable) one dedicated unit. No other services are touched.
                self._write(f"{units}/{SERVICE}", unit)
                self._run(f"systemd-analyze --user verify {shlex.quote(f'{units}/{SERVICE}')}")
                self._run("systemctl --user daemon-reload")
                self._set(deployment="starting")
                self._run(f"systemctl --user stop {SERVICE}")
                self._run(f"mv -- {shlex.quote(pending)} {shlex.quote(main)}")
                self._write(str(root / "run.log"), "")
                self._set(logs=[], exit_code=None)
                self._run(f"systemctl --user start {SERVICE}")
                self._set(deployment="succeeded")
                self._refresh()
            except Exception as error:
                self._failure(error, deployment=True)
            finally:
                self._set(busy=False)

    def _refresh(self):
        raw = self._run(
            f"systemctl --user show {SERVICE} --no-pager "
            "--property=LoadState,ActiveState,SubState,MainPID,ExecMainCode,ExecMainStatus"
        )
        info = program_status(raw)
        logs = []
        with self._sftp() as sftp:
            try:
                with sftp.file(f"{self.config.remote_dir}/run.log", "rb") as source:
                    size = source.stat().st_size
                    offset = max(0, size - LOG_BYTES)
                    source.seek(offset)
                    lines = source.read(LOG_BYTES).decode("utf-8", errors="replace").splitlines()
                    logs = (lines[1:] if offset else lines)[-1000:]
            except FileNotFoundError:
                pass
        self._set(**info, logs=logs, connected=True, connection_error=None)
        self._last_poll = time.monotonic()

    def status(self) -> dict:
        state = self.snapshot()
        if self._closed or not state["connected"] or state["busy"] or time.monotonic() - self._last_poll < 0.8:
            return state
        if self._io_lock.acquire(blocking=False):
            try:
                if not self.snapshot()["busy"]:
                    self._open()
                    self._refresh()
            except Exception as error:
                self._failure(error)
            finally:
                self._io_lock.release()
        return self.snapshot()

    def close(self):
        self._closed = True
        if self._worker:
            self._worker.join(timeout=3)
        # Close even when an operation timed out; never stop the remote service.
        self._disconnect()
