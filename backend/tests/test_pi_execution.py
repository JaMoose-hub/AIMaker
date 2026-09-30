"""FIFO/handoff acceptance with fake SSH; no real hardware."""
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pi import router
from app.pi_execution import PiExecution
from app.pi_deploy import RemoteCommandError, SERVICE
from tests.test_component_testing import FakePi, ManualTests, context, ended


class QueuePi(FakePi):
    def __init__(self):
        super().__init__()
        self._home = "/home/test"
        self.deployments = []
        self.stop_fails = False
        self.foreign_test = False

    def check_environment(self, imports=(), devices=(), code=None):
        self.commands.append("preflight")
        self._open()
        if code is not None:
            compile(code, "queued.py", "exec")
        if self.fail == "environment":
            raise RemoteCommandError("No module named luma")

    def assert_no_component_service(self):
        if self.foreign_test:
            raise RemoteCommandError("unknown component service is active")

    def _run(self, command, timeout=20):
        if self.stop_fails and command == f"systemctl --user stop {SERVICE}":
            raise EOFError("stop reply lost")
        return super()._run(command, timeout)

    def deploy(self, code, **kwargs):
        assert not self._test_reserved
        assert self.snapshot()["program"] not in {"running", "starting", "stopping", "unknown"}
        self.deployments.append(code)
        self._set(deployment="succeeded", program="running", pid=100 + len(self.deployments), invocation_id=str(len(self.deployments)))
        return {"ok": True, "status": self.snapshot()}


@pytest.fixture
def queue(tmp_path):
    pi = QueuePi()
    tests = ManualTests(pi, tmp_path / "runs.json")
    queue = PiExecution(pi, tests)
    queue._ensure_worker = lambda: None
    return queue


def job(queue, rid):
    return next(j for j in queue.snapshot()["jobs"] if j["id"] == rid)


def consent(queue, rid):
    current = job(queue, rid)
    assert current["state"] == "awaiting_confirmation"
    queue.action(rid, "confirm", current["owner"])


def test_fifo_checks_before_stop_and_no_automatic_restore(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original")
    first = queue.submit("deploy", {"code": "print('first')"})
    second = queue.submit("test", context())
    queue._tick()
    assert queue.pi.commands[0] == "preflight"
    assert job(queue, first)["state"] == "awaiting_confirmation"
    assert job(queue, second)["state"] == "queued"
    assert not any("stop " in c for c in queue.pi.commands)
    consent(queue, first); queue._tick()
    assert queue.pi.deployments == ["print('first')"]
    queue._tick()
    consent(queue, second); queue._tick()
    run = queue.tests._active()
    assert run and run["program_stopped"]
    queue.tests._tick(run)
    ended(queue.tests, run)
    queue._tick()
    assert job(queue, second)["state"] == "finished"
    assert queue.pi.snapshot()["program"] == "stopped"
    assert queue.pi.deployments == ["print('first')"]


def test_deploy_behind_test_waits_for_confirmed_remote_stop(queue):
    first = queue.submit("test", context())
    queue._tick(); run = queue.tests._active(); queue.tests._tick(run)
    second = queue.submit("deploy", {"code": "print('project')"})
    queue._tick(); consent(queue, second); queue._tick()
    assert run["pending"] == "stop" and run["reserved"]
    assert not queue.pi.deployments
    queue._tick()
    assert not queue.pi.deployments
    queue.tests._tick(run)  # actual inactive remote service, not just button press
    queue._tick()
    assert job(queue, first)["state"] == "finished"
    assert run["outcome"] == "inconclusive" and run["reason"] == "cancelled"
    assert len(queue.pi.deployments) == 1


def test_two_deployments_each_need_fresh_process_consent(queue):
    first = queue.submit("deploy", {"code": "print(1)"})
    second = queue.submit("deploy", {"code": "print(2)"})
    queue._tick(); queue._tick()
    assert job(queue, first)["state"] == "finished"
    assert job(queue, second)["state"] == "awaiting_confirmation"
    with pytest.raises(ValueError, match="handoff_changed"):
        queue.action(second, "confirm", "program:other")
    consent(queue, second)
    queue.pi._set(invocation_id="changed")
    queue._tick()
    assert len(queue.pi.deployments) == 1
    assert job(queue, second)["owner"] == "program:changed"
    consent(queue, second); queue._tick()
    assert queue.pi.deployments == ["print(1)", "print(2)"]


def test_active_upload_not_interrupted(queue):
    queue.pi._set(busy=True)
    rid = queue.submit("test", context())
    queue._tick()
    assert job(queue, rid)["state"] == "queued"
    assert not queue.pi.commands and not queue.tests.runs


@pytest.mark.parametrize("failure", ["environment", "syntax", "wiring"])
def test_failed_preflight_preserves_current_program(queue, failure):
    queue.pi._set(program="running", pid=41)
    queue.pi.fail = "environment" if failure == "environment" else None
    payload = context(key="changed") if failure == "wiring" else {"code": "if :" if failure == "syntax" else "print(1)"}
    if failure == "wiring": payload["wires"] = []
    rid = queue.submit("test" if failure == "wiring" else "deploy", payload)
    queue._tick()
    assert job(queue, rid)["state"] == "failed"
    assert queue.pi.snapshot()["program"] == "running"
    assert not any("stop " in c for c in queue.pi.commands)


def test_lost_stop_reply_blocks_next_until_reconciliation(queue):
    queue.pi._set(program="running", pid=41)
    rid = queue.submit("deploy", {"code": "print(1)"})
    later = queue.submit("test", context())
    queue._tick(); consent(queue, rid)
    queue.pi.stop_fails = True
    queue._tick()
    assert job(queue, rid)["state"] == "blocked"
    assert job(queue, later)["state"] == "queued"
    assert not queue.pi.deployments
    queue.pi.fail = "offline"
    queue._tick()
    assert not queue.pi.deployments
    queue.pi.fail = None; queue.pi.stop_fails = False
    queue.pi._set(connected=True, program="stopped")
    queue._tick()
    assert len(queue.pi.deployments) == 1


def test_duplicate_tabs_idempotency_frozen_code_and_cancel(queue):
    payload = {"code": "print('original')"}
    ids = []
    threads = [threading.Thread(target=lambda: ids.append(queue.submit("deploy", payload, "same"))) for _ in range(10)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(set(ids)) == 1
    assert queue.submit("deploy", payload, "different-tab") == ids[0]
    payload["code"] = "print('edited')"
    with pytest.raises(ValueError, match="request_id_conflict"):
        queue.submit("deploy", payload, "same")
    later = queue.submit("deploy", payload)
    queue.action(later, "cancel")
    queue._tick(); queue._tick()
    assert queue.pi.deployments == ["print('original')"]
    assert job(queue, later)["state"] == "cancelled"
    assert "payload" not in json.dumps(queue.snapshot())


def test_cancel_during_preflight_does_not_stop_or_launch(queue):
    rid = queue.submit("deploy", {"code": "print(1)"})
    queue.pi.check_environment = lambda *args: queue.action(rid, "cancel")
    queue._tick()
    assert job(queue, rid)["state"] == "cancelled"
    assert not queue.pi.deployments


def test_cancel_after_handoff_stop_prevents_replacement_launch(queue):
    queue.tests.start(context()); old = queue.tests._active(); queue.tests._tick(old)
    rid = queue.submit("deploy", {"code": "print('replacement')"})
    queue._tick(); consent(queue, rid); queue._tick()
    assert job(queue, rid)["state"] == "stopping"
    assert old["pending"] == "stop"
    queue.action(rid, "cancel")
    queue.tests._tick(old)
    queue._tick()
    assert job(queue, rid)["state"] == "cancelled"
    assert not queue.pi.deployments


def test_unmanaged_remote_test_blocks_deploy_without_killing_it(queue):
    queue.pi.foreign_test = True
    rid = queue.submit("deploy", {"code": "print(1)"})
    queue._tick()
    assert job(queue, rid)["state"] == "failed"
    assert not queue.pi.deployments
    assert not any("stop " in c for c in queue.pi.commands)


def test_new_backend_does_not_replay_queue_or_abandon_remote_test(queue):
    queue.submit("deploy", {"code": "print('must not replay')"})
    queue.tests.start(context()); queue.tests._tick(queue.tests._active())
    restored = ManualTests(queue.pi, queue.tests.store)
    restarted = PiExecution(queue.pi, restored)
    assert restarted.snapshot()["jobs"] == []
    assert restored._active()["remote_launched"] and queue.pi._test_reserved


def test_api_uses_same_fifo_for_both_entrypoints(queue):
    app = FastAPI(); app.include_router(router)
    app.state.pi_deployer, app.state.component_tests, app.state.pi_execution = queue.pi, queue.tests, queue
    with TestClient(app) as client:
        first = client.post("/api/pi/component-tests", json={**context(), "request_id":"first"}).json()
        second = client.post("/api/pi/deploy", json={"code":"print(1)","request_id":"second"}).json()
        assert first["ok"] and second["ok"]
        jobs = client.get("/api/pi/status").json()["execution"]["jobs"]
        assert [j["kind"] for j in jobs] == ["test", "deploy"]
        assert not queue.pi.files and not queue.pi.deployments
        assert client.post(f"/api/pi/execution/{second['job_id']}/action", json={"action":"cancel"}).json()["ok"]


def test_deployment_unit_shares_component_runner_lock():
    from tests.test_pi_deploy import RecordingPi, finish
    pi = RecordingPi(); pi.deploy("print(1)"); finish(pi)
    unit = pi.files[f"/home/pet/.config/systemd/user/{SERVICE}"]
    assert "/usr/bin/flock --nonblock --no-fork" in unit
    assert f"{pi.config.remote_dir}/component-tests/hardware.lock" in unit


def test_new_test_owner_requires_new_consent_and_new_stop_command(queue):
    queue.tests.start(context()); old = queue.tests._active(); queue.tests._tick(old)
    rid = queue.submit("deploy", {"code":"print(1)"})
    queue._tick(); consent(queue, rid); queue._tick(); queue.tests._tick(old)
    queue.tests.start(context(key="different")); current = queue.tests._active(); queue.tests._tick(current)
    queue._tick()
    assert job(queue,rid)["owner"] == "test:" + current["id"]
    assert not current["pending"]
    consent(queue,rid); queue._tick()
    assert current["pending"] == "stop"
    assert not queue.pi.deployments


def test_active_queue_entry_survives_many_cancelled_jobs(queue):
    first = queue.submit("deploy", {"code":"print('first')"})
    for index in range(45):
        rid = queue.submit("deploy", {"code":f"print({index})"})
        queue.action(rid,"cancel")
    assert job(queue,first)["state"] == "queued"


def test_standalone_stop_is_owner_bound_and_preserves_records(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original", logs=["saved output"])
    previous = queue.submit("deploy", {"code": "print('keep draft')"})
    queue.action(previous, "cancel")
    before = queue.snapshot()
    # Fake SSH must reflect actual inactive PID just as systemctl show does.
    refresh = queue.pi._refresh
    def inactive_refresh():
        refresh()
        if queue.pi.snapshot()["program"] == "stopped":
            queue.pi._set(pid=None)
    queue.pi._refresh = inactive_refresh
    result = queue.stop_project("program:original")
    assert result["ok"] and result["status"]["program"] == "stopped"
    assert result["status"]["pid"] is None and not result["status"]["busy"]
    assert result["status"]["logs"] == ["saved output"]
    assert queue.snapshot() == before and not queue.tests.runs and not queue.pi.deployments
    assert queue.pi.commands == [f"systemctl --user stop {SERVICE}"]
    assert queue.stop_project("program:original")["ok"]  # no second stop command
    assert len(queue.pi.commands) == 1


@pytest.mark.parametrize("blocker", ["queue", "busy", "test", "trial", "reservation", "foreign", "changed", "unknown", "no_identity", "stale_pid", "closed"])
def test_standalone_stop_rejects_unverified_or_changed_work(queue, blocker):
    queue.pi._set(program="running", pid=41, invocation_id="original")
    expected = {
        "queue": "stop_queue_active", "busy": "stop_program_busy", "test": "stop_test_active",
        "trial": "stop_test_active", "reservation": "stop_test_active", "changed": "stop_owner_changed",
        "unknown": "stop_state_unknown", "no_identity": "stop_state_unknown", "closed": "executor_closed",
    }
    if blocker == "queue": queue.submit("deploy", {"code": "print(1)"})
    elif blocker == "busy": queue.pi._set(busy=True)
    elif blocker == "test": queue.tests.start(context())
    elif blocker == "trial":
        class ActiveTrial:
            def status(self): return {"active": {"id": "trial"}, "results": [], "test_busy": True}
        queue.trials = ActiveTrial()
    elif blocker == "reservation": queue.pi._test_reserved = "remote-test"
    elif blocker == "foreign": queue.pi.foreign_test = True
    elif blocker == "changed": queue.pi._set(invocation_id="new-program")
    elif blocker == "unknown": queue.pi._set(program="unknown")
    elif blocker == "no_identity": queue.pi._set(program="starting", pid=None, invocation_id="")
    elif blocker == "stale_pid": queue.pi._set(program="stopped")
    elif blocker == "closed": queue.closed.set()
    if blocker in {"foreign", "stale_pid"}:
        assert not queue.stop_project("program:original")["ok"]
    else:
        with pytest.raises(ValueError, match=expected[blocker]): queue.stop_project("program:original")
    assert not any("stop " in command for command in queue.pi.commands)
    assert not queue.pi.deployments
    assert queue.pi.snapshot()["busy"] == (blocker == "busy")


def test_standalone_stop_rechecks_remote_owner_not_cached_status(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original")
    queue.pi._refresh = lambda: queue.pi._set(invocation_id="remote-replacement", pid=42)
    with pytest.raises(ValueError, match="stop_owner_changed"):
        queue.stop_project("program:original")
    assert not queue.pi.commands


def test_standalone_stop_lost_reply_is_not_success_or_retried(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original")
    queue.pi.stop_fails = True
    result = queue.stop_project("program:original")
    assert not result["ok"] and result["status"]["program"] == "unknown"
    assert not result["status"]["busy"] and not queue.pi.deployments
    assert "private-test-password" not in json.dumps(result)


def test_standalone_stop_disconnect_redacts_status_and_keeps_output(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original", logs=["preserved output"])
    queue.pi.fail = "offline"
    result = queue.stop_project("program:original")
    assert not result["ok"] and not result["status"]["connected"]
    assert result["status"]["program"] == "unknown" and result["status"]["logs"] == ["preserved output"]
    assert "private-test-password" not in json.dumps(result)
    assert not queue.pi.commands and not queue.pi.deployments


def test_standalone_stop_reservation_prevents_concurrent_hardware_start(queue):
    queue.pi._set(program="running", pid=41, invocation_id="original")
    results = []
    refresh = queue.pi._refresh
    def checking_refresh():
        refresh()
        if queue.pi.snapshot()["program"] == "running":
            results.append(queue.tests.start(context()))
        else:
            queue.pi._set(pid=None)
    queue.pi._refresh = checking_refresh
    assert queue.stop_project("program:original")["ok"]
    assert results and all(not result["ok"] and result["error"] == "resource_busy" for result in results)
    assert not queue.tests.runs


def test_standalone_stop_api_requires_exact_program_owner_and_executor(queue):
    app = FastAPI(); app.include_router(router)
    app.state.pi_deployer, app.state.pi_execution = queue.pi, queue
    with TestClient(app) as client:
        for body in ({}, {"owner": ""}, {"owner": "test:abc"}, {"owner": "program:"}):
            assert client.post("/api/pi/stop", json=body).status_code == 422
        queue.pi._set(program="running", pid=41, invocation_id="new")
        response = client.post("/api/pi/stop", json={"owner": "program:old"})
        assert response.status_code == 409 and response.json()["detail"] == "stop_owner_changed"
        queue.pi._set(program="stopped", pid=None)
        result = client.post("/api/pi/stop", json={"owner": "program:old"}).json()
        assert result["ok"] and "execution" in result["status"]
        del app.state.pi_execution
        response = client.post("/api/pi/stop", json={"owner": "program:old"})
        assert response.status_code == 503 and response.json()["detail"] == "stop_backend_restart_required"
    assert not queue.pi.commands and not queue.pi.deployments
