"""Deployment failure ordering and API tests; never contact real hardware."""
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import paramiko
import pytest

from app.api.pi import router
from app.config import PiDeployConfig
from app.pi_deploy import PiDeployer, RemoteCommandError, SERVICE, program_status


class RecordingPi(PiDeployer):
    def __init__(self):
        super().__init__(PiDeployConfig())
        self._home = "/home/pet"
        self._set(connected=True, program="running", pid=41)
        self.commands = []
        self.files = {}
        self.fail_venv = False
        self.gate = None

    def _open(self):
        pass

    def _write(self, path, contents):
        self.files[path] = contents

    def _run(self, command, timeout=20):
        self.commands.append(command)
        if "compile(" in command:
            try:
                compile(self.files[f"{self.config.remote_dir}/main.pending.py"], "main.pending.py", "exec")
            except SyntaxError as error:
                raise RemoteCommandError(str(error)) from error
        if "venv --system-site-packages" in command:
            if self.gate:
                assert self.gate.wait(3)
            if self.fail_venv:
                raise RemoteCommandError("venv installation failed")
        return ""

    def _refresh(self):
        self._set(program="running", pid=42, logs=["real script output"])


def finish(pi):
    pi._worker.join(3)
    assert not pi._worker.is_alive()
    return pi.snapshot()


def test_code_upload_and_order_single_user_service():
    pi = RecordingPi()
    code = "print(" + repr('中文 ` $() " quoted') + ")\r\n"
    assert pi.deploy(code)["ok"]
    status = finish(pi)
    assert status["deployment"] == "succeeded"
    assert not status["busy"]
    assert pi.files[f"{pi.config.remote_dir}/main.pending.py"] == code.replace("\r\n", "\n")
    checks = next(i for i, cmd in enumerate(pi.commands) if "compile(" in cmd)
    stop = pi.commands.index(f"systemctl --user stop {SERVICE}")
    replace = next(i for i, cmd in enumerate(pi.commands) if cmd.startswith("mv -- "))
    start = pi.commands.index(f"systemctl --user start {SERVICE}")
    assert checks < stop < replace < start
    assert not any("enable" in cmd for cmd in pi.commands)
    assert not any("reset-failed" in cmd for cmd in pi.commands)  # inactive units may be unloaded
    unit = pi.files[f"/home/pet/.config/systemd/user/{SERVICE}"]
    assert "Restart=no" in unit and "KillMode=control-group" in unit
    assert "WorkingDirectory=/home/pet/Desktop/Pi_deployer\n" in unit


@pytest.mark.parametrize("code,fail_venv", [("if :", False), ("print('ok')", True)])
def test_preflight_failure_preserves_running_program(code, fail_venv):
    pi = RecordingPi()
    pi.fail_venv = fail_venv
    pi.deploy(code)
    state = finish(pi)
    assert state["deployment"] == "failed" and state["error"]
    assert state["program"] == "running" and state["pid"] == 41
    assert not any(f"stop {SERVICE}" in cmd for cmd in pi.commands)
    assert not any(cmd.startswith("mv -- ") for cmd in pi.commands)


def test_duplicate_deploy_is_rejected_and_status_remains_responsive():
    pi = RecordingPi()
    pi.gate = threading.Event()
    try:
        assert pi.deploy("print('first')")["ok"]
        assert not pi.deploy("print('second')")["ok"]
        before = time.monotonic()
        assert pi.status()["busy"]
        assert time.monotonic() - before < 0.2
    finally:
        pi.gate.set()
        finish(pi)


def test_disconnect_never_reports_stale_program_as_running():
    pi = RecordingPi()
    pi._refresh = lambda: (_ for _ in ()).throw(EOFError("SSH disconnected"))
    state = pi.status()
    assert not state["connected"] and state["program"] == "unknown"
    assert state["pid"] is None and state["connection_error"] == "SSH disconnected"


def test_failed_authentication_clears_busy_and_does_not_return_password():
    class BadClient:
        def load_system_host_keys(self): pass
        def set_missing_host_key_policy(self, policy): pass
        def connect(self, *args, **kwargs): raise paramiko.AuthenticationException("Authentication failed")
        def close(self): pass
    pi = PiDeployer(PiDeployConfig(password="test-secret"), BadClient)
    result = pi.connect()
    assert not result["ok"] and not result["status"]["busy"]
    assert not result["status"]["connected"]
    assert "test-secret" not in str(result)
    assert not pi.deploy("print('ok')")["ok"]


@pytest.mark.parametrize("raw,expected,exit_code", [
    ("LoadState=not-found\nActiveState=inactive", "not_deployed", None),
    ("LoadState=bad-setting\nActiveState=inactive", "failed", None),
    ("LoadState=loaded\nActiveState=active\nMainPID=123", "running", None),
    ("LoadState=loaded\nActiveState=failed\nExecMainCode=1\nExecMainStatus=1", "failed", 1),
    ("LoadState=loaded\nActiveState=inactive\nExecMainCode=1\nExecMainStatus=0", "exited", 0),
    ("LoadState=loaded\nActiveState=inactive\nExecMainCode=0", "stopped", None),
])
def test_remote_process_state_is_independent_from_upload_success(raw, expected, exit_code):
    state = program_status(raw)
    assert state["program"] == expected and state["exit_code"] == exit_code


def test_api_contract_and_background_deployment():
    app = FastAPI()
    app.include_router(router)
    pi = RecordingPi()
    app.state.pi_deployer = pi
    with TestClient(app) as client:
        assert client.get("/api/pi/status").json()["host"] == "192.168.50.174"
        assert client.post("/api/pi/deploy", json={"code": ""}).status_code == 422
        assert client.post("/api/pi/deploy", json={"code": "print('from editor')"}).json()["ok"]
        finish(pi)
        assert client.get("/api/pi/status").json()["deployment"] == "succeeded"


@pytest.mark.parametrize("failure", ["dependency", "device"])
def test_tft_preflight_failure_keeps_current_service_running(failure):
    class FailedDisplayPi(RecordingPi):
        def _run(self, command, timeout=20):
            result = super()._run(command, timeout)
            if failure == "dependency" and "importlib.import_module" in command:
                raise RemoteCommandError("No module named luma")
            if failure == "device" and "test -r /dev/spidev0.0" in command:
                raise RemoteCommandError("No SPI device")
            return result
    pi = FailedDisplayPi()
    pi.deploy("print('test')", imports=["luma.lcd", "PIL", "spidev"], devices=["/dev/spidev0.0"])
    state = finish(pi)
    assert state["deployment"] == "failed" and state["program"] == "running"
    assert not any(f"stop {SERVICE}" in command for command in pi.commands)


def test_project_tft_requirements_are_from_catalog_not_browser():
    from app.designs import CATALOG
    app = FastAPI()
    app.include_router(router)
    pi = RecordingPi()
    app.state.pi_deployer = pi
    with TestClient(app) as client:
        response = client.post("/api/pi/deploy", json={"code": "print('test')", "project": {
            "component_ids": ["hc-sr04", "mrd-tf240-8p-cs"], "catalog_version": CATALOG["version"]}})
        assert response.json()["ok"]
        assert finish(pi)["deployment"] == "succeeded"
    assert any("importlib.import_module" in cmd and "luma.lcd" in cmd for cmd in pi.commands)
    spi_check = next(i for i, cmd in enumerate(pi.commands) if "test -r /dev/spidev0.0" in cmd)
    assert spi_check < pi.commands.index(f"systemctl --user stop {SERVICE}")
