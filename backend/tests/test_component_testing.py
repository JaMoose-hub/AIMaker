"""Isolated software acceptance; never contacts SSH, camera, or GPIO."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pi import router
from app.component_testing import ComponentTests, REMOTE_LIMIT, redact
from app.config import PiDeployConfig
from app.designs import CATALOG, profile_versions, wiring_for
from app.pi_deploy import PiDeployer, RemoteCommandError, SERVICE


spec = importlib.util.spec_from_file_location("test_runner", Path(__file__).parents[1] / "app/runtime/component_test.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FakePi(PiDeployer):
    def __init__(self):
        super().__init__(PiDeployConfig(password="private-test-password"))
        self._set(connected=True, program="stopped")
        self.commands, self.files = [], {}
        self.raw = "LoadState=loaded\nActiveState=active\nMainPID=10\nExecMainStatus=0"
        self.result = None
        self.fail = None

    def _open(self):
        if self.fail == "offline":
            raise EOFError("private-test-password disconnected")

    def _run(self, command, timeout=20):
        self.commands.append(command)
        if self.fail == "environment" and " -c " in command:
            raise RemoteCommandError("ModuleNotFoundError: No module named lgpio")
        if command == f"systemctl --user stop {SERVICE}":
            self._set(program="stopped")
        if "show boardvision-test-" in command:
            return self.raw
        if "stop boardvision-test-" in command:
            self.raw = "LoadState=loaded\nActiveState=inactive\nMainPID=0\nExecMainStatus=0"
        if "journalctl" in command:
            return "failure token=private-token private-test-password"
        return ""

    def _write(self, path, contents):
        self.files[path] = contents

    def _refresh(self):
        pass


class ManualTests(ComponentTests):
    def _ensure_worker(self):
        pass

    def _read_result(self, directory):
        return self.pi.result


@pytest.fixture
def tests(tmp_path):
    return ManualTests(FakePi(), tmp_path / "tests.json")


def context(cid="hc-sr04", key="current-wiring"):
    return dict(project_id="project", revision=1, component_id=cid,
                guide_key=key, catalog_version=CATALOG["version"],
                profile_versions=profile_versions([cid]), wires=wiring_for([cid]))


def begin(tests, cid="hc-sr04"):
    assert tests.start(context(cid))["ok"]
    run = tests._active()
    tests._tick(run)
    return run


def ended(tests, run, outcome="passed", reason=None, exit_code=0):
    tests.pi.raw = f"LoadState=loaded\nActiveState=inactive\nMainPID=0\nExecMainStatus={exit_code}"
    tests.pi.result = dict(run_id=run["id"], phase="finished", outcome=outcome, reason=reason,
                          heartbeat_at=time.time(), samples={"near":{"count":8,"median_cm":15}})
    tests._poll(run)


def test_template_isolated_versioned_bounded_and_catalog_pins(tests):
    run = begin(tests)
    assert run["pins"] == {"TRIG":17, "ECHO":18}
    assert run["template_version"] and run["wiring_hash"]
    command = next(c for c in tests.pi.commands if c.startswith("systemd-run"))
    assert f"RuntimeMaxSec={REMOTE_LIMIT}" in command and "KillMode=control-group" in command
    assert all("/component-tests/" in path for path in tests.pi.files)
    assert not any("main.py" in c or f"start {SERVICE}" in c for c in tests.pi.commands)
    assert "visual_code" not in tests.snapshot()["active"]
    assert "private-test-password" not in json.dumps(tests.snapshot())


def test_preflight_before_consent_and_no_automatic_restart(tests):
    tests.pi._set(program="running")
    run = begin(tests)
    assert run["phase"] == "awaiting_stop_consent"
    assert not tests.pi.files and not any("stop " in c for c in tests.pi.commands)
    tests.action(run["id"], "stop_project", run["guide_key"])
    tests._tick(run)
    assert run["program_stopped"] and run["remote_launched"]
    ended(tests, run)
    assert run["outcome"] == "passed" and not run["reserved"]
    assert tests.pi.snapshot()["program"] == "stopped"
    assert not any(f"start {SERVICE}" in c for c in tests.pi.commands)


def test_environment_failure_does_not_stop_original(tests):
    tests.pi._set(program="running")
    tests.pi.fail = "environment"
    tests.start(context())
    run = tests._active()
    ComponentTests._ensure_worker(tests)
    tests.worker.join(3)
    assert not run["reserved"] and run["reason"] == "missing_dependency"
    assert run["failed_phase"] == "preflight"
    assert not any("stop " in c for c in tests.pi.commands)


@pytest.mark.parametrize("cid", ["hc-sr04", "mrd-tf240-8p-cs"])
def test_mutex_duplicate_tabs_and_deployment(tests, cid):
    results = []
    threads = [threading.Thread(target=lambda: results.append(tests.start(context(cid))["ok"])) for _ in range(5)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert results.count(True) == 1 and len(results) == 5
    assert not tests.pi.deploy("print('must not run')")["ok"]
    run = tests._active()
    tests.action(run["id"], "stop", "")
    tests._tick(run)
    assert not tests.pi._test_reserved
    assert tests.start(context())["ok"]


def test_deployment_blocks_test_before_any_write(tests):
    tests.pi._set(busy=True)
    assert tests.start(context())["error"] == "resource_busy"
    assert not tests.pi.files


def test_live_stop_confirms_service_stopped_before_release(tests):
    run = begin(tests)
    tests.action(run["id"], "stop", "")
    assert run["reserved"]
    tests._tick(run)
    assert run["reason"] == "cancelled" and not run["reserved"]
    assert any(f"stop boardvision-test-{run['id']}" in c for c in tests.pi.commands)


def test_disconnect_retains_reservation_and_recovers_without_launch(tests):
    run = begin(tests)
    before = sum(c.startswith("systemd-run") for c in tests.pi.commands)
    tests.pi.fail = "offline"
    ComponentTests._ensure_worker(tests)
    time.sleep(.1)
    tests.close()
    assert run["reason"] == "connection_lost" and run["reserved"]
    assert "private-test-password" not in run["detail"]
    assert not tests.start(context())["ok"]
    tests.pi.fail = None
    resumed = ManualTests(tests.pi, tests.store)
    assert resumed._active()["phase"] == "reconnecting"
    ended(resumed, resumed._active(), "inconclusive", "no_echo")
    assert sum(c.startswith("systemd-run") for c in tests.pi.commands) == before
    assert not resumed.pi._test_reserved


def test_unknown_remote_state_does_not_free_hardware(tests):
    run = begin(tests)
    tests.pi.raw = "unexpected"
    tests._poll(run)
    assert run["reserved"] and run["reason"] == "remote_state_unknown"


def test_stale_foreign_result_and_exit_without_result_never_pass(tests):
    run = begin(tests)
    tests.pi.result = {"run_id":"old", "phase":"finished", "outcome":"passed"}
    tests.pi.raw = "LoadState=loaded\nActiveState=inactive\nExecMainStatus=0"
    tests._poll(run)
    assert run["outcome"] == "inconclusive" and run["reason"] == "no_result"
    assert "private-test-password" not in run["detail"] and "private-token" not in run["detail"]


def test_visual_success_requires_current_code_and_human_color_confirmation(tests):
    run = begin(tests, "mrd-tf240-8p-cs")
    ended(tests, run, "awaiting_confirmation")
    assert run["outcome"] == "awaiting_confirmation" and run["reserved"]
    with pytest.raises(ValueError, match="stale_test"):
        tests.action(run["id"], "visual", "other-wiring", code=run["visual_code"], appearance="normal")
    tests.action(run["id"], "visual", run["guide_key"], code=run["visual_code"], appearance="normal")
    assert run["outcome"] == "passed" and run["evidence"] == "user_visual_confirmation"
    next_run = begin(tests, "mrd-tf240-8p-cs")
    assert next_run["visual_code"] != run["visual_code"]
    ended(tests, next_run, "awaiting_confirmation")
    tests.action(next_run["id"], "visual", next_run["guide_key"], code=run["visual_code"], appearance="normal")
    assert next_run["reason"] == "wrong_visual_code"


@pytest.mark.parametrize("appearance", ["black", "white", "abnormal", None])
def test_display_symptoms_and_no_color_confirmation_do_not_pass(tests, appearance):
    run = begin(tests, "mrd-tf240-8p-cs")
    ended(tests, run, "awaiting_confirmation")
    tests.action(run["id"], "visual", run["guide_key"], code=run["visual_code"], appearance=appearance)
    assert run["outcome"] == "failed"


def test_invalidation_keeps_stop_control_and_rejects_late_confirmation(tests):
    run = begin(tests, "mrd-tf240-8p-cs")
    tests.action(run["id"], "invalidate", "")
    assert run["reserved"] and run["invalidated"]
    with pytest.raises(ValueError, match="stale_test"):
        tests.action(run["id"], "visual", run["guide_key"], code=run["visual_code"], appearance="normal")
    tests._tick(run)
    assert not run["reserved"] and run["reason"] == "wiring_changed"


@pytest.mark.parametrize("reason", ["timeout", "no_echo", "resource_busy", "program_error", "reader_error"])
def test_remote_failure_reasons_not_guessed_as_miswiring(tests, reason):
    run = begin(tests)
    ended(tests, run, "inconclusive" if reason in {"timeout", "no_echo"} else "failed", reason)
    assert run["reason"] == reason and run["outcome"] != "passed"


def test_hard_systemd_timeout_and_heartbeat_stall(tests):
    run = begin(tests)
    run["launched_at"] = time.time() - 10
    tests._poll(run)
    assert run["reason"] == "no_progress" and run["reserved"]
    tests.pi.raw = "LoadState=loaded\nActiveState=failed\nResult=timeout\nExecMainStatus=15"
    tests._poll(run)
    assert run["reason"] == "timeout" and not run["reserved"]


def test_near_far_commands_require_ready_phase_and_run_binding(tests):
    run = begin(tests)
    with pytest.raises(ValueError, match="invalid_phase"):
        tests.action(run["id"], "near", run["guide_key"])
    tests.pi.result = dict(run_id=run["id"], phase="awaiting_near", heartbeat_at=time.time())
    tests._poll(run)
    tests.action(run["id"], "near", run["guide_key"])
    tests._tick(run)
    command = json.loads(next(v for k,v in tests.pi.files.items() if k.endswith("command.json")))
    assert command == {"run_id":run["id"], "action":"near"}


def test_changed_catalog_wiring_profile_rejected(tests):
    for field in ("wires", "catalog_version", "profile_versions"):
        body = context()
        body[field] = [] if field == "wires" else {} if field == "profile_versions" else "old"
        with pytest.raises(ValueError): tests.start(body)
    assert not tests.pi.files


def test_api_contract_status_start_stop_and_validation(tests):
    app = FastAPI()
    app.state.component_tests, app.state.pi_deployer = tests, tests.pi
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/pi/component-tests").json()["active"] is None
        response = client.post("/api/pi/component-tests", json=context())
        assert response.status_code == 200
        rid = response.json()["active"]["id"]
        assert client.post(f"/api/pi/component-tests/{rid}/action",json={"action":"stop"}).status_code == 200
        assert client.post("/api/pi/component-tests", json={**context(),"component_id":"hw-123"}).status_code == 422
        assert client.post(f"/api/pi/component-tests/{rid}/action",json={"action":"visual","code":"old"}).status_code == 422
        assert client.post("/api/pi/component-tests",json={**context(),"catalog_version":"old"}).status_code == 409


@pytest.mark.parametrize("near,far,expected", [([10]*5,[15]*5,"passed"),([10]*4,[30]*8,"inconclusive"),
    ([10]*8,[14.9]*8,"inconclusive"),([],[],"inconclusive"),([10,11,10,10,100],[30]*5,"passed")])
def test_distance_criteria(near, far, expected):
    assert runner.distance_result(near, far)[0] == expected


def test_collection_never_reuses_cached_echo_and_rejects_invalid_values(monkeypatch):
    clock = [100_000_000_000]
    monkeypatch.setattr(runner.time,"monotonic_ns",lambda:clock[0])
    monkeypatch.setattr(runner.time,"sleep",lambda seconds:clock.__setitem__(0, clock[0]+int(seconds*1e9)))
    class Sensor:
        max_distance = 4
        latest = (99_000_000_000, .1)
    class Report:
        def update(self, **values): pass
    sensor = Sensor()
    assert runner.collect(sensor, Report(), "near") == []
    sensor.latest = (clock[0]+1, .1)
    assert runner.collect(sensor, Report(), "near") == [40]
    for bad in (float('nan'), float('inf'), 0, -1, 1):
        sensor.latest = (clock[0]+1,bad)
        assert runner.collect(sensor,Report(),"far") == []


def test_redaction():
    assert redact("password=foo token=bar sk-abcdefghijklmnop private", "private") == "password=[redacted] token=[redacted] [redacted] [redacted]"
    assert "abc123" not in redact('Authorization: Bearer abc123')
    assert "secret" not in redact('{"password":"secret"}')


def test_stop_during_preflight_does_not_launch(tests):
    tests.start(context())
    run = tests._active()
    original = tests.pi._refresh
    def concurrent_stop():
        original()
        tests.action(run["id"],"stop","")
    tests.pi._refresh = concurrent_stop
    tests._tick(run)
    assert not run["reserved"]
    assert not any(c.startswith("systemd-run") for c in tests.pi.commands)


def test_unloaded_transient_service_still_uses_matching_terminal_result(tests):
    run = begin(tests)
    tests.pi.raw = "LoadState=not-found\nActiveState=inactive\nMainPID=0"
    tests.pi.result = dict(run_id=run["id"],phase="finished",outcome="passed")
    tests._poll(run)
    assert run["outcome"] == "passed" and not run["reserved"]


def test_latest_result_of_each_module_survives_many_retests_and_restart(tests):
    first = begin(tests)
    ended(tests,first)
    for n in range(110):
        duplicate = deepcopy(first)
        duplicate.update(id=f"mock-{n}",component_id="mrd-tf240-8p-cs")
        tests.runs.append(duplicate)
    tests._save()
    restored = ManualTests(tests.pi,tests.store)
    assert any(r["id"]==first["id"] for r in restored.snapshot("project")["results"])
    assert len(restored.runs)==101


def test_display_runner_rgb_code_and_cleanup_before_confirmation(monkeypatch):
    import sys
    import types
    events, frames, texts = [], [], []
    class Factory:
        def close(self): events.append("factory_closed")
    class Device:
        size = (240,320)
        def display(self,image):
            frames.append(image.copy())
            events.append("frame_sent")
    class Display:
        def __init__(self,pins,factory): self.device=Device()
        def text(self,draw,position,text,**kwargs): texts.append(text)
        def close(self): events.append("display_closed")
    class Report:
        def update(self,**values): events.append(values["phase"])
    monkeypatch.setitem(sys.modules,"gpiozero.pins.lgpio",types.SimpleNamespace(LGPIOFactory=Factory))
    monkeypatch.setitem(sys.modules,"display",types.SimpleNamespace(WiringDisplay=Display))
    monkeypatch.setattr(runner.time,"sleep",lambda seconds:events.append(("sleep",seconds)))
    result=runner.display_test({"pins":{},"visual_code":"0732"},Report())
    assert result["outcome"] == "awaiting_confirmation"
    assert [frame.getpixel((0,0)) for frame in frames[:3]] == [(255,0,0),(0,255,0),(0,0,255)]
    assert len(frames)==4 and "0732" in texts
    assert events[-2:] == ["display_closed","factory_closed"]
    code_start = max(i for i, event in enumerate(events) if event == "frame_sent")
    assert events[code_start+1:-2] == ["display_code", ("sleep",1)] * 15
    assert sum(event[1] for event in events if isinstance(event, tuple)) == 18


def test_code_viewing_keeps_lock_and_is_not_automatic_pass(tests):
    run = begin(tests, "mrd-tf240-8p-cs")
    tests.pi.result = dict(run_id=run["id"], phase="display_code", outcome="running",
                          heartbeat_at=time.time(), last_progress_at=time.time())
    tests._poll(run)
    assert run["phase"] == "display_code" and run["outcome"] == "running" and run["reserved"]
    assert tests.pi._test_reserved == run["id"]
    assert not tests.start(context("mrd-tf240-8p-cs"))["ok"]
    tests.pi.result["last_progress_at"] -= 10
    tests._poll(run)
    assert run["reason"] == "no_progress"
    ended(tests, run, "awaiting_confirmation")
    assert run["phase"] == "awaiting_visual" and run["outcome"] == "awaiting_confirmation"


def test_sensor_runner_waits_each_phase_reuses_sensor_and_releases_it(monkeypatch):
    import sys
    import types
    events, sensors = [], []
    class Factory:
        def close(self): events.append("factory_closed")
    class Sensor:
        def __init__(self,**kwargs): events.append((kwargs["echo"],kwargs["trigger"]))
        def __enter__(self): return self
        def __exit__(self,*args): events.append("sensor_closed")
    class Report:
        def wait_ready(self,phase,deadline,check_health):
            check_health()
            events.append("ready_"+phase)
        def update(self,**values): pass
    monkeypatch.setitem(sys.modules,"gpiozero",types.SimpleNamespace(DistanceSensor=Sensor))
    monkeypatch.setitem(sys.modules,"gpiozero.pins.lgpio",types.SimpleNamespace(LGPIOFactory=Factory))
    def collect(sensor,reporter,phase,seconds=5,check_health=None):
        assert seconds==5
        assert sensor.latest is None
        check_health()
        sensors.append(sensor)
        return [15 if phase=="near" else 30]*6
    monkeypatch.setattr(runner,"collect",collect)
    result=runner.sensor_test({"pins":{"ECHO":18,"TRIG":17}},Report(),999)
    assert result["outcome"]=="passed"
    assert sensors[0] is sensors[1]
    assert events==["ready_near",(18,17),"ready_far","sensor_closed","factory_closed"]


def test_collection_resets_phase_counters_and_rejects_previous_phase_sample(monkeypatch):
    clock = [100_000_000_000]
    monkeypatch.setattr(runner.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+int(seconds*1e9)))
    class Sensor:
        max_distance = 4
        latest = (clock[0]+1, .1)
    class Report:
        state = {}
        def update(self, **values): self.state.update(values)
    sensor, report = Sensor(), Report()
    assert runner.collect(sensor, report, "near") == [40]
    assert report.state["sample_count"] == 1
    assert runner.collect(sensor, report, "far") == []
    assert report.state["latest"] is None
    assert report.state["latest_valid_at"] is None
    assert report.state["sample_count"] == 0


@pytest.mark.parametrize("failure_phase", ["awaiting_far", "sampling_far", "cleanup"])
def test_real_background_callback_error_aborts_sensor_test_and_releases_once(monkeypatch, failure_phase):
    """Reproduce the real lgpio thread failure, not just a fake result JSON."""
    import sys
    import types
    events, phases, captured = [], [], []
    previous_hook = lambda args: captured.append((args.exc_type, str(args.exc_value)))
    monkeypatch.setattr(threading, "excepthook", previous_hook)
    def crash_callback():
        def callback():
            raise TypeError("unsupported operand type(s) for &: 'NoneType' and 'int'")
        thread = threading.Thread(target=callback, name="lgpio-callback")
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
    class Factory:
        def close(self):
            events.append("factory_closed")
            if failure_phase == "cleanup": crash_callback()
    class Sensor:
        def __init__(self, **kwargs): events.append("sensor_opened")
        def __enter__(self): return self
        def __exit__(self, *args): events.append("sensor_closed")
    class Report:
        def wait_ready(self, phase, deadline, check_health):
            phases.append("awaiting_"+phase)
            if failure_phase == "awaiting_"+phase: crash_callback()
            check_health()
        def update(self, **values): pass
    def collect(sensor, reporter, phase, seconds=5, check_health=None):
        phases.append("sampling_"+phase)
        if failure_phase == "sampling_"+phase: crash_callback()
        check_health()
        return [15 if phase == "near" else 30]*6
    monkeypatch.setitem(sys.modules, "gpiozero", types.SimpleNamespace(DistanceSensor=Sensor))
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", types.SimpleNamespace(LGPIOFactory=Factory))
    monkeypatch.setattr(runner, "collect", collect)
    with pytest.raises(runner.ReaderError, match="lgpio-callback: TypeError") as error:
        runner.sensor_test({"pins":{"ECHO":18,"TRIG":17}}, Report(), 999)
    assert runner.classify_error(error.value) == "reader_error"
    assert events == ["sensor_opened", "sensor_closed", "factory_closed"]
    assert len(captured) == 1
    assert threading.excepthook is previous_hook


def test_wait_ready_checks_background_health_even_without_user_command(tmp_path):
    reporter = runner.Reporter(tmp_path, "test-run")
    def failed_reader(): raise runner.ReaderError("lgpio callback died")
    try:
        with pytest.raises(runner.ReaderError):
            reporter.wait_ready("far", time.monotonic()+10, failed_reader)
    finally:
        reporter.finish(outcome="failed", reason="reader_error")
    data = json.loads((tmp_path/"result.json").read_text())
    assert data["reason"] == "reader_error" and data["failed_phase"] == "awaiting_far"


def test_collection_checks_health_even_after_enough_samples(monkeypatch):
    clock = [100_000_000_000]
    monkeypatch.setattr(runner.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+int(seconds*1e9)))
    class Sensor:
        max_distance = 4
        @property
        def latest(self): return (clock[0], .1)
    class Report:
        count = 0
        def update(self, **values): self.count = values.get("sample_count", self.count)
    report = Report()
    def health():
        if report.count >= 6: raise runner.ReaderError("callback stopped")
    with pytest.raises(runner.ReaderError):
        runner.collect(Sensor(), report, "far", check_health=health)


def test_sensor_read_timestamp_precedes_driver_read_and_factory_error_restores_hook(monkeypatch):
    import sys
    import types
    clock, seen = [100], []
    monkeypatch.setattr(runner.time, "monotonic_ns", lambda: clock[0])
    class Factory:
        def close(self): pass
    class Sensor:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def _read(self):
            clock[0] += 10
            return .1
    class Report:
        def wait_ready(self, phase, deadline, check_health): check_health()
        def update(self, **values): pass
    def collect(sensor, reporter, phase, seconds=5, check_health=None):
        sensor._read()
        seen.append(sensor.latest)
        return [15 if phase == "near" else 30]*6
    monkeypatch.setitem(sys.modules, "gpiozero", types.SimpleNamespace(DistanceSensor=Sensor))
    driver = types.SimpleNamespace(LGPIOFactory=Factory)
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", driver)
    monkeypatch.setattr(runner, "collect", collect)
    assert runner.sensor_test({"pins":{"ECHO":18,"TRIG":17}}, Report(), 999)["outcome"] == "passed"
    assert seen == [(100, .1), (110, .1)]
    before = threading.excepthook
    def unavailable(): raise RuntimeError("GPIO busy")
    driver.LGPIOFactory = unavailable
    with pytest.raises(RuntimeError, match="GPIO busy"):
        runner.sensor_test({"pins":{"ECHO":18,"TRIG":17}}, Report(), 999)
    assert threading.excepthook is before
