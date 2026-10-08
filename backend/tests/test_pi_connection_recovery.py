"""Management-only reconnect checks; no real SSH, GPIO or deployment."""
import threading

import paramiko
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pi import router
from app.config import PiDeployConfig
from app.pi_deploy import PiDeployer, RECONNECT_INTERVAL_S, SERVICE


class ReadOnlyPi(PiDeployer):
    def __init__(self):
        super().__init__(PiDeployConfig())
        self.opens = 0
        self.commands = []
        self.errors = []
        self.entered = self.release = None

    def _open(self):
        self.opens += 1
        if self.entered:
            self.entered.set()
            assert self.release.wait(2)
        if self.errors:
            raise self.errors.pop(0)

    def _sftp(self):
        class Files:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def normalize(self, path):
                assert path == "."
                return "/home/pet"
            def file(self, path, mode):
                assert mode == "rb"
                raise FileNotFoundError(path)
        return Files()

    def _run(self, command, timeout=20):
        self.commands.append(command)
        if command == "hostname": return "raspberrypi"
        if command == "python3 --version": return "Python 3.11.2"
        assert command.startswith(f"systemctl --user show {SERVICE} "), "recovery must never start/stop/install/write"
        return "LoadState=loaded\nActiveState=active\nMainPID=321\nExecMainCode=0\nInvocationID=existing-program"

    def _write(self, *args):
        raise AssertionError("Recovery cannot write remote files")


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("app.pi_deploy.time.monotonic", lambda: now[0])
    return now


def test_cold_status_does_not_initiate_first_time_connection(clock):
    pi = ReadOnlyPi()
    assert not pi.status()["connected"]
    assert pi.opens == 0 and pi.commands == []


def test_status_restores_requested_connection_and_reconciles_existing_program_without_replay(clock):
    pi = ReadOnlyPi()
    assert pi.connect()["ok"]
    pi._set(error="saved deployment failure")
    clock[0] += 1
    pi.errors = [EOFError("SSH interrupted")]
    lost = pi.status()
    assert not lost["connected"] and lost["pid"] is None and lost["program"] == "unknown"
    attempts = pi.opens
    assert not pi.status()["connected"] and pi.opens == attempts
    clock[0] += RECONNECT_INTERVAL_S + .01
    recovered = pi.status()
    assert recovered["connected"] and recovered["pid"] == 321
    assert recovered["invocation_id"] == "existing-program"
    assert recovered["connection_error"] is None
    assert recovered["error"] == "saved deployment failure"
    assert pi._worker is None and recovered["deployment"] == "idle"


def test_failed_manual_network_connection_can_recover_but_repeated_polls_are_throttled(clock):
    pi = ReadOnlyPi()
    pi.errors = [TimeoutError(), TimeoutError()]
    assert not pi.connect()["ok"]
    for _ in range(5): assert not pi.status()["connected"]
    assert pi.opens == 1
    clock[0] += RECONNECT_INTERVAL_S + .01
    assert not pi.status()["connected"] and pi.opens == 2
    for _ in range(5): assert not pi.status()["connected"]
    assert pi.opens == 2
    clock[0] += RECONNECT_INTERVAL_S + .01
    assert pi.status()["connected"] and pi.opens == 3


@pytest.mark.parametrize("kind", ["authentication", "host_key"])
def test_identity_failures_require_explicit_reconnect_not_automatic_authentication_retries(clock, kind):
    pi = ReadOnlyPi()
    key = paramiko.RSAKey.generate(1024) if kind == "host_key" else None
    pi.errors = [paramiko.AuthenticationException("Authentication failed") if key is None
                 else paramiko.BadHostKeyException("raspberrypi", key, key)]
    assert not pi.connect()["ok"]
    clock[0] += 100
    assert not pi.status()["connected"] and pi.opens == 1
    assert pi.connect()["ok"] and pi.opens == 2


@pytest.mark.parametrize("guard", ["busy", "closed", "io_lock"])
def test_reconnect_never_competes_with_owned_work_or_a_closed_client(clock, guard):
    pi = ReadOnlyPi()
    pi._connection_requested = True
    if guard == "busy": pi._set(busy=True)
    if guard == "closed": pi.close()
    if guard == "io_lock": pi._io_lock.acquire()
    try:
        assert not pi.status()["connected"]
        assert pi.opens == 0 and pi.commands == []
    finally:
        if guard == "io_lock": pi._io_lock.release()


def test_two_status_clients_share_one_recovery_and_do_not_queue_duplicate_attempts(clock):
    pi = ReadOnlyPi()
    pi._connection_requested = True
    pi.entered, pi.release = threading.Event(), threading.Event()
    worker = threading.Thread(target=pi.status)
    worker.start()
    try:
        assert pi.entered.wait(1)
        assert not pi.status()["connected"] and pi.opens == 1
    finally:
        pi.release.set()
        worker.join(2)
    assert not worker.is_alive() and pi.snapshot()["connected"]
    assert pi.status()["connected"] and pi.opens == 1


def test_refresh_status_api_can_restore_connection_without_posting_any_hardware_action(clock):
    pi = ReadOnlyPi()
    assert pi.connect()["ok"]
    pi._failure(TimeoutError("temporary timeout"))
    clock[0] += RECONNECT_INTERVAL_S + .01
    app = FastAPI()
    app.include_router(router)
    app.state.pi_deployer = pi
    with TestClient(app) as client:
        result = client.get("/api/pi/status").json()
    assert result["connected"] and result["pid"] == 321
    assert pi._worker is None and result["deployment"] == "idle"
