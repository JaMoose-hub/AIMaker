"""Persisted, single-Pi component tests. No camera or cloud dependency."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import threading
import time
import uuid

from app.designs import CATALOG, MODULES, profile_versions, wiring_for
from app.pi_deploy import SERVICE, RemoteCommandError

TEMPLATE_VERSION = "component-test-v3"
TERMINAL = {"passed", "failed", "inconclusive"}
REMOTE_LIMIT = 180


def redact(text, password=""):
    text = str(text)
    if password:
        text = text.replace(password, "[redacted]")
    text = re.sub(r"(?:sk-[\w-]{12,}|gh[pousr]_[\w]{15,}|github_pat_[\w]+)", "[redacted]", text)
    text = re.sub(r'''(?i)((?:password|token|api[_-]?key|authorization)["']?\s*[:=]\s*)(?:bearer\s+)?(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r"\1[redacted]", text)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----", "[redacted key]", text)
    return text[-4000:]


def wire_key(wires):
    return sorted((w["componentId"], w["componentPin"], w["boardPin"], w["connectionKind"]) for w in wires)


class ComponentTests:
    def __init__(self, pi, store=None):
        self.pi = pi
        self.store = Path(store or Path(__file__).resolve().parents[1] / "runs/component-tests.json")
        self.target = hashlib.sha256(f"{pi.config.host}:{pi.config.port}:{pi.config.username}:{pi.config.remote_dir}".encode()).hexdigest()
        self.lock = threading.RLock()
        self.runs = []
        self.worker = None
        self.closed = threading.Event()
        try:
            self.runs = json.loads(self.store.read_text(encoding="utf-8"))["runs"]
            if not isinstance(self.runs, list) or any(not isinstance(r, dict) or "id" not in r for r in self.runs):
                self.runs = []
        except (OSError, ValueError, KeyError, TypeError):
            pass
        for run in self.runs:
            if run.get("reserved"):
                if run.get("target") == self.target and run.get("remote_launched"):
                    run.update(outcome="inconclusive", reason="connection_lost", phase="reconnecting", pending=None)
                    pi._test_reserved = run["id"]
                else:
                    run.update(reserved=False, outcome="inconclusive", reason="interrupted", phase="finished")

    def _save(self):
        latest = {(r["target"], r["project_id"], r["component_id"]): r["id"] for r in self.runs}
        keep = set(latest.values()) | {r["id"] for r in self.runs[-100:]} | {r["id"] for r in self.runs if r.get("reserved")}
        self.runs = [r for r in self.runs if r["id"] in keep]
        self.store.parent.mkdir(parents=True, exist_ok=True)
        pending = self.store.with_suffix(".tmp")
        pending.write_text(json.dumps({"runs": self.runs}, ensure_ascii=False), encoding="utf-8")
        pending.replace(self.store)

    def _active(self):
        return next((r for r in reversed(self.runs) if r.get("reserved") and r["target"] == self.target), None)

    def _public(self, run):
        return {k: deepcopy(v) for k, v in run.items() if k not in {"visual_code", "pins", "pending", "target"}}

    def snapshot(self, project_id=None):
        with self.lock:
            active = self._active()
            records = [r for r in self.runs if r["target"] == self.target and (project_id is None or r["project_id"] == project_id)]
            latest = {(r["project_id"], r["component_id"]):r["id"] for r in records}
            keep = set(latest.values()) | {r["id"] for r in records[-20:]}
            return dict(active=self._public(active) if active else None,
                        results=[self._public(r) for r in records if r["id"] in keep],
                        connected=self.pi.snapshot()["connected"], test_busy=bool(active))

    def status(self, project_id=None):
        self._ensure_worker()
        return self.snapshot(project_id)

    def _ensure_worker(self):
        with self.lock:
            if not self.closed.is_set() and self._active() and (not self.worker or not self.worker.is_alive()):
                self.worker = threading.Thread(target=self._loop, name="pi-component-test", daemon=True)
                self.worker.start()

    def validate(self, context):
        cid = context["component_id"]
        if cid not in MODULES or context["catalog_version"] != CATALOG["version"]:
            raise ValueError("catalog_changed")
        expected = wiring_for([cid])
        if wire_key(context["wires"]) != wire_key(expected):
            raise ValueError("wiring_changed")
        if context["profile_versions"].get(cid) != profile_versions([cid])[cid]:
            raise ValueError("profile_changed")
        return expected

    def start(self, context):
        cid = context["component_id"]
        expected = self.validate(context)
        with self.lock, self.pi._state_lock:
            if self.closed.is_set():
                return dict(ok=False, error="connection_lost", **self.snapshot(context["project_id"]))
            if self.pi._test_reserved or self.pi._state.busy:
                return dict(ok=False, error="resource_busy", **self.snapshot(context["project_id"]))
            rid = uuid.uuid4().hex
            old_codes = {r.get("visual_code") for r in self.runs[-100:]}
            code = f"{secrets.randbelow(10000):04d}"
            while code in old_codes:
                code = f"{secrets.randbelow(10000):04d}"
            options = {code}
            while len(options) < 4:
                options.add(f"{secrets.randbelow(10000):04d}")
            options = list(options)
            secrets.SystemRandom().shuffle(options)
            run = dict(id=rid, project_id=context["project_id"], revision=context["revision"],
                component_id=cid, guide_key=context["guide_key"], target=self.target, target_id=self.target[:12],
                wiring_hash=hashlib.sha256(json.dumps(wire_key(expected)).encode()).hexdigest(),
                template_version=TEMPLATE_VERSION, created_at=time.time(), outcome="running", phase="preflight",
                reason=None, detail="", logs=[], samples={}, latest=None, heartbeat_at=None, exit_code=None,
                reserved=True, remote_launched=False, program_stopped=False, invalidated=False,
                visual_code=code, options=options if cid != "hc-sr04" else [], pending=None,
                pins={w["componentPin"]: int(w["boardPin"][4:]) for w in expected if w["boardPin"].startswith("GPIO")})
            self.pi._test_reserved = rid
            self.runs.append(run)
            self._save()
        self._ensure_worker()
        return dict(ok=True, **self.snapshot(context["project_id"]))

    def _update(self, run, **values):
        with self.lock:
            if values.get("phase", run["phase"]) != run["phase"]:
                run["logs"] = (run["logs"] + [f"{time.strftime('%H:%M:%S')} {values['phase']}"])[-60:]
            run.update(values, updated_at=time.time())
            self._save()

    def _finish(self, run, outcome, reason=None, **values):
        with self.lock, self.pi._state_lock:
            if reason:
                run["failed_phase"] = run["phase"]
            run.update(values, outcome=outcome, reason=reason, reserved=False, phase="finished",
                       pending=None, latest=None, finished_at=time.time())
            if self.pi._test_reserved == run["id"]:
                self.pi._test_reserved = None
            self._save()

    def action(self, rid, action, guide_key, *, code=None, appearance=None):
        with self.lock:
            run = next((r for r in self.runs if r["id"] == rid and r["target"] == self.target), None)
            if not run:
                raise ValueError("test_not_found")
            if action not in {"stop", "invalidate"} and (run["guide_key"] != guide_key or run["invalidated"]):
                raise ValueError("stale_test")
            if action == "invalidate":
                run["invalidated"] = True
                if not run["reserved"]:
                    self._finish(run, "inconclusive", "wiring_changed")
                else:
                    run["pending"] = "stop"
            elif not run["reserved"]:
                raise ValueError("test_finished")
            elif action == "visual":
                if run["outcome"] != "awaiting_confirmation" or run["phase"] != "awaiting_visual":
                    raise ValueError("not_awaiting_visual")
                if appearance == "normal" and code == run["visual_code"]:
                    self._finish(run, "passed", evidence="user_visual_confirmation")
                else:
                    reason = {"black": "display_black", "white": "display_white", "abnormal": "display_abnormal"}.get(appearance, "wrong_visual_code")
                    self._finish(run, "failed", reason)
            elif action == "stop":
                run["pending"] = "stop"
            elif run["pending"] is not None:
                raise ValueError("action_pending")
            elif action == "stop_project" and run["phase"] == "awaiting_stop_consent":
                run["pending"] = action
            elif action in {"near", "far"} and run["phase"] == "awaiting_" + action:
                run["pending"] = action
            else:
                raise ValueError("invalid_phase")
            self._save()
        self._ensure_worker()
        return dict(ok=True, **self.snapshot(run["project_id"]))

    def _paths(self, run):
        root = PurePosixPath(self.pi.config.remote_dir)
        if not root.is_absolute() or root.name != "Pi_deployer":
            raise RemoteCommandError("Invalid deployment directory")
        return str(root / "component-tests" / run["id"]), str(root / ".venv/bin/python")

    def _preflight(self, run):
        directory, python = self._paths(run)
        imports = MODULES[run["component_id"]]["runtime"]["imports"]
        devices = MODULES[run["component_id"]]["runtime"]["devices"]
        check = ("import importlib,os,glob,json; "
                 + "; ".join(f"importlib.import_module({item!r})" for item in imports)
                 + f"; devices={devices!r}; "
                 "assert glob.glob('/dev/gpiochip*'), 'gpio_device_missing'; "
                 "assert any(os.access(p,os.R_OK|os.W_OK) for p in glob.glob('/dev/gpiochip*')), 'device_permission'; "
                 "assert all(os.path.exists(p) for p in devices), 'spi_missing'; "
                 "assert all(os.access(p,os.R_OK|os.W_OK) for p in devices), 'device_permission'; "
                 "print('environment_ready')")
        self.pi._run("command -v systemd-run >/dev/null && systemctl --user show-environment >/dev/null")
        self.pi._run(f"{shlex.quote(python)} -c {shlex.quote(check)}")
        self.pi._refresh()
        if self.pi.snapshot()["program"] in {"running", "starting", "stopping"}:
            self._update(run, phase="awaiting_stop_consent", outcome="awaiting_confirmation", reason=None)
        else:
            self._launch(run)

    def _launch(self, run):
        if run.get("pending") == "stop" or run["invalidated"]:
            self._finish(run, "inconclusive", "wiring_changed" if run["invalidated"] else "cancelled")
            return
        self.pi.assert_no_component_service()
        directory, python = self._paths(run)
        self.pi._run(f"mkdir -p {shlex.quote(directory)}")
        runtime = Path(__file__).parent / "runtime"
        for name, source in (("runner.py", "component_test.py"), ("display.py", "ili9341_display.py")):
            self.pi._write(directory + "/" + name, (runtime / source).read_text(encoding="utf-8"))
        self.pi._write(directory + "/config.json", json.dumps(dict(run_id=run["id"], component_id=run["component_id"],
            pins=run["pins"], visual_code=run["visual_code"])))
        if run.get("pending") == "stop" or run["invalidated"]:
            self._finish(run, "inconclusive", "wiring_changed" if run["invalidated"] else "cancelled")
            return
        # Persist uncertain launch *before* sending the command. A transport
        # timeout must not free the reservation and allow a duplicate runner.
        self._update(run, remote_launched=True, phase="starting", outcome="running", launched_at=time.time())
        unit = "boardvision-test-" + run["id"]
        self.pi._run(f"systemd-run --user --unit={unit} --service-type=exec --property=RuntimeMaxSec={REMOTE_LIMIT} "
            "--property=TimeoutStopSec=5 --property=KillMode=control-group --property=Restart=no "
            f"--property=WorkingDirectory={shlex.quote(directory)} {shlex.quote(python)} -u "
            f"{shlex.quote(directory + '/runner.py')} {shlex.quote(directory)}")

    def _read_result(self, directory):
        with self.pi._sftp() as sftp:
            try:
                with sftp.file(directory + "/result.json", "rb") as source:
                    return json.loads(source.read(16000).decode("utf-8"))
            except FileNotFoundError:
                return None

    def _poll(self, run):
        directory, python = self._paths(run)
        command = (f"systemctl --user show boardvision-test-{run['id']}.service --no-pager "
                   "--property=LoadState,ActiveState,MainPID,ExecMainCode,ExecMainStatus,Result")
        # Successful transient units can be unloaded. Accept explicit not-found /
        # inactive, never a transport failure or an unavailable user manager.
        probe = (f"import subprocess,sys; p=subprocess.run({command!r}.split(),capture_output=True,text=True,timeout=10); "
                 "print(p.stdout,end=''); absent='LoadState=not-found' in p.stdout and 'ActiveState=inactive' in p.stdout; "
                 "print(p.stderr if p.returncode and not absent else '',end=''); sys.exit(0 if absent else p.returncode)")
        raw = self.pi._run(f"{shlex.quote(python)} -c {shlex.quote(probe)}")
        props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        alive = props.get("ActiveState") in {"active", "activating", "deactivating"}
        data = self._read_result(directory)
        if data and data.get("run_id") != run["id"]:
            data = None
        if data:
            self._update(run, heartbeat_at=data.get("heartbeat_at"), latest=data.get("latest"),
                         latest_valid_at=data.get("latest_valid_at"),
                         samples=data.get("samples", {}), sample_count=data.get("sample_count", 0),
                         detail=redact(data.get("detail", ""), self.pi.config.password.get_secret_value()))
        if alive:
            heartbeat = data.get("heartbeat_at", run["launched_at"]) if data else run["launched_at"]
            phase = data.get("phase", "starting") if data else "starting"
            progress = data.get("last_progress_at", heartbeat) if data else heartbeat
            stalled = time.time() - heartbeat > 5 or (
                phase in {"starting", "sampling_near", "sampling_far", "display_red", "display_lime", "display_blue", "display_code"}
                and time.time() - progress > 8)
            self._update(run, phase=data.get("phase", "starting") if data else "starting", outcome="running",
                         reason="no_progress" if stalled else None)
            return
        # Terminal result is trusted only after the process group has stopped.
        if not props or props.get("ActiveState") not in {"inactive", "failed"}:
            self._update(run, outcome="inconclusive", reason="remote_state_unknown")
            return
        exit_code = int(props.get("ExecMainStatus", "0"))
        self._update(run, exit_code=exit_code)
        if run.get("pending") == "stop" or run["invalidated"]:
            self._finish(run, "inconclusive", "wiring_changed" if run["invalidated"] else "cancelled")
        elif props.get("Result") == "timeout":
            self._finish(run, "inconclusive", "timeout")
        elif data and data.get("phase") == "finished" and exit_code == 0:
            if data.get("outcome") == "awaiting_confirmation":
                self._update(run, phase="awaiting_visual", outcome="awaiting_confirmation", reason=None,
                             visual_deadline=time.time() + 300, latest=None)
            elif data.get("outcome") in TERMINAL:
                self._finish(run, data["outcome"], data.get("reason"),
                             **({"failed_phase": data["failed_phase"]} if data.get("failed_phase") else {}))
            else:
                self._finish(run, "inconclusive", "invalid_result")
        else:
            journal = self.pi._run(f"journalctl --user -u boardvision-test-{run['id']}.service -n 25 --no-pager -o cat")
            self._update(run, detail=redact(journal, self.pi.config.password.get_secret_value()))
            self._finish(run, "failed" if exit_code else "inconclusive", "program_error" if exit_code else "no_result")

    def _tick(self, run):
        with self.pi._io_lock:
            self.pi._open()
            self.pi._set(connected=True, connection_error=None)
            pending = run.get("pending")
            if pending == "stop":
                if run["remote_launched"]:
                    self._poll(run)
                    if run["reserved"]:
                        self.pi._run(f"systemctl --user stop boardvision-test-{run['id']}.service")
                        self._poll(run)
                else:
                    self._finish(run, "inconclusive", "wiring_changed" if run["invalidated"] else "cancelled")
            elif pending == "stop_project":
                self._update(run, program_stop_requested=True)
                self.pi._run(f"systemctl --user stop {SERVICE}")
                self.pi._refresh()
                if self.pi.snapshot()["program"] in {"running", "starting", "stopping"}:
                    raise RemoteCommandError("Original program did not stop")
                # Do not erase a stop/invalidate action received while SSH was busy.
                self._update(run, program_stopped=True, pending="stop" if run.get("pending") == "stop" else None)
                self._launch(run)
            elif pending in {"near", "far"}:
                directory, _ = self._paths(run)
                # Runner ignores incomplete JSON writes and commands from other runs.
                self.pi._write(directory + "/command.json", json.dumps(dict(run_id=run["id"], action=pending)))
                self._update(run, pending=None, phase="sampling_" + pending, outcome="running")
            elif run["phase"] == "preflight":
                self._preflight(run)
            elif run["phase"] == "awaiting_stop_consent":
                if time.time() - run["created_at"] > 300:
                    self._finish(run, "inconclusive", "timeout")
            elif run["phase"] == "awaiting_visual":
                if time.time() > run["visual_deadline"]:
                    self._finish(run, "inconclusive", "timeout")
            else:
                self._poll(run)

    def _loop(self):
        while not self.closed.is_set():
            with self.lock:
                run = self._active()
            if run is None:
                return
            try:
                self._tick(run)
            except Exception as error:
                detail = redact(error, self.pi.config.password.get_secret_value())
                if run["remote_launched"]:
                    self.pi._failure(RemoteCommandError(detail) if isinstance(error, RemoteCommandError) else RuntimeError(detail))
                    self._update(run, outcome="inconclusive", reason="connection_lost", detail=detail, latest=None)
                else:
                    text = str(error).lower()
                    reason = ("spi_missing" if "spi_missing" in text else "device_permission" if "permission" in text
                              else "missing_dependency" if any(s in text for s in ("no module", "not found", "no such file", "gpio_device_missing"))
                              else "program_error" if isinstance(error, RemoteCommandError) else "connection_lost")
                    if not isinstance(error, RemoteCommandError):
                        self.pi._failure(RuntimeError(detail))
                    self._finish(run, "inconclusive", reason, detail=detail)
            self.closed.wait(1)

    def close(self):
        self.closed.set()
        if self.worker:
            self.worker.join(3)
        # The remote systemd lifetime stays active after the web backend closes.
