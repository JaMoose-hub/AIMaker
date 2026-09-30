"""Collaborative debug orchestration uses frozen fake evidence and fake Pi jobs."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.debug_sessions import router
from app.debug_capture import current_debug_camera
from app.debug_sessions import DebugSessions
from app.designs import demo_design


class Bridge:
    def __init__(self):
        self.calls = []
        self.images = []

    def generate(self, prompt, schema, **kwargs):
        self.calls.append((prompt, kwargs))
        self.images.append([Path(path).read_bytes() for path in kwargs.get("image_paths", [])])
        kwargs.get("response_metadata", {}).update(model=kwargs.get("model") or "test-model",
                                                   completed_at=time.time(), elapsed_ms=5)
        if "stage1_color" in schema["required"]:
            return dict(stage1_color="red", stage1_text="A1", stage2_color="green", stage2_text="B2",
                        stage3_color="blue", stage3_text="C3", stage4_color="black", stage4_text="1234",
                        visibility="clear")
        return dict(seen="零件與目標可見", visibility="clear", suggested_action="test_hc" if "Component: hc-sr04." in prompt else "test_tft",
                    explanation="固定測試可確認實際功能", next_step="請將目標放到感測器正前方，確認回波是否改變。")


class Cases:
    def __init__(self):
        self.cases = {}

    def diagnose(self, context, case_id=None):
        key = case_id or "case1"
        self.cases[key] = dict(id=key, status="ready", issues=[], evidence=dict(pi=dict(program="stopped")),
                               history=[], candidate=None)
        return deepcopy(self.cases[key])

    def get(self, key):
        return deepcopy(self.cases[key])

    def analyse(self, key, context, model, effort):
        self.cases[key]["analysis"] = dict(facts="fake", next_step="inspect")
        return self.get(key)


class FakeTests:
    target = "pi-target"

    def __init__(self):
        self.runs = []
        self.actions = []

    def validate(self, payload):
        assert payload["component_id"] in {"hc-sr04", "mrd-tf240-8p-cs"}
        assert payload["guide_key"]

    def snapshot(self, project_id=None):
        runs = [r for r in self.runs if project_id is None or r["project_id"] == project_id]
        return dict(results=deepcopy(runs), active=None)

    def action(self, run_id, action, guide_key):
        run = next(r for r in self.runs if r["id"] == run_id)
        assert run["guide_key"] == guide_key
        self.actions.append((run_id, action))
        if action in {"near", "far"}:
            run["phase"] = "sampling_" + action
        if action == "stop":
            run.update(phase="finished", outcome="inconclusive", reason="cancelled", reserved=False)

    def compare_camera_observation(self, run_id, phase_seq, observed_text, observed_color=None):
        assert any(r["id"] == run_id for r in self.runs)
        assert phase_seq in {1, 2, 3, 4}
        return dict(matched=True, code_matched=True, color_matched=True, phase_seq=phase_seq,
                    verification_source="camera_advisory", human_confirmation_required=True)


class Trials:
    def __init__(self):
        self.runs = []

    def validate(self, context):
        assert context["project"]["id"]

    def snapshot(self, project_id=None):
        return dict(results=deepcopy([r for r in self.runs if project_id is None or r["project_id"] == project_id]))

    def action(self, run_id, action):
        assert any(r["id"] == run_id for r in self.runs)


class Executor:
    def __init__(self):
        self.jobs = []

    def submit(self, kind, payload, request_id):
        old = next((j for j in self.jobs if j["request_id"] == request_id), None)
        if old:
            return old["id"]
        job = dict(id=f"job{len(self.jobs)+1}", kind=kind, state="queued", run_id=None,
                   component_id=payload.get("component_id"), request_id=request_id)
        self.jobs.append(job)
        return job["id"]

    def snapshot(self):
        return dict(jobs=deepcopy(self.jobs))

    def action(self, job_id, action):
        job = next(j for j in self.jobs if j["id"] == job_id)
        assert action == "cancel"
        job["state"] = "cancelled"


def _context():
    project = demo_design()
    project["id"] = "collab-debug"
    confirmations = {}
    for wire in project["wiring"]:
        confirmations[wire["id"]] = dict(signature="|".join(wire[key] for key in
            ("componentId", "componentPin", "boardPin", "connectionKind")),
            mode="camera", at="2026-09-25T00:00:00.000Z")
    keys = {}
    for cid in project["component_ids"]:
        rows = [[confirmations[wire["id"]]["signature"], confirmations[wire["id"]]["at"]]
                for wire in project["wiring"] if wire["componentId"] == cid]
        keys[cid] = json.dumps([project["id"], project["revision"], 0, project["catalog_version"],
                               project["profile_versions"][cid], rows], ensure_ascii=False, separators=(",", ":"))
    return dict(project=project, code=project["code"],
                test_keys=keys, guide_confirmations=confirmations, guide_run=0, entry={})


@pytest.fixture
def setup(tmp_path):
    tests, trials, queue, bridge, cases = FakeTests(), Trials(), Executor(), Bridge(), Cases()
    revision = SimpleNamespace(board_id="raspberry-pi-5", runtime_revision=7)
    pi = SimpleNamespace(config=SimpleNamespace(password=SimpleNamespace(get_secret_value=lambda: "private")))
    state = SimpleNamespace(component_tests=tests, integration_trials=trials, pi_execution=queue,
                            design_service=SimpleNamespace(bridge=bridge), debug_cases=cases, pi_deployer=pi,
                            config=SimpleNamespace(camera=SimpleNamespace(source="device")),
                            source=SimpleNamespace(current_index=0, device_name="fake-camera", capture_mode="default"),
                            runtime_manager=SimpleNamespace(snapshot=lambda: revision),
                            glasses_stream=SimpleNamespace(snapshot=lambda: {"active": False, "state": "idle"}))
    sequence = 0

    def capture(state, target, earliest_ms=None):
        nonlocal sequence
        sequence += 1
        return ({"overview": b"jpeg-" + str(sequence).encode()},
                dict(source="device", target=target, runtime_revision=revision.runtime_revision,
                     camera_id=current_debug_camera(state),
                     frame_id=sequence, seq=sequence, ts_ms=time.monotonic()*1000,
                     captured_at="2026-09-25T00:00:00+00:00", size=[640, 480], sha256="fake",
                     quality=dict(framing_ready=True, score=1, warnings=[]), stability=dict(stable=True)))

    service = DebugSessions(state, tmp_path / "sessions.json", capture, autostart=False)
    return service, state


def _run(run_id, cid, context, phase, outcome="running"):
    return dict(id=run_id, project_id=context["project"]["id"], component_id=cid,
                guide_key=context["test_keys"][cid], phase=phase, outcome=outcome, reserved=True,
                target_id="pi-target"[:12], camera_assisted=cid == "mrd-tf240-8p-cs",
                invalidated=False, reason=None)


def _diagnosed(service, context, symptom="距離沒有變化"):
    session = service.create(context, symptom, request_id="create1")
    service.tick(session["id"])
    service.tick(session["id"])
    return session["id"]


def test_create_resume_binding_and_read_only_diagnosis(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    assert service.get(sid)["status"] == "awaiting_capture"
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls
    assert service.create(context, "new tab", request_id="create2")["id"] == sid
    assert service.active()["active"]["id"] == sid
    assert service.active("another-project")["active"]["id"] == sid
    assert service.active("another-project")["same_project"] is False
    with pytest.raises(ValueError, match="session_active"):
        changed = deepcopy(context)
        changed["code"] += "\n# changed"
        service.create(changed, "other project", request_id="create3")


def test_hc_ready_gates_and_queue_idempotency(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_ready"
    assert len(state.design_service.bridge.calls) == 1
    result = service.action(sid, "ready", "near-ready", context=context)
    assert result["status"] == "testing" and len(state.pi_execution.jobs) == 1
    assert service.action(sid, "ready", "near-ready", context=context)["id"] == sid
    assert len(state.pi_execution.jobs) == 1
    state.pi_execution.jobs[0].update(state="running", run_id="hc1")
    state.component_tests.runs.append(_run("hc1", "hc-sr04", context, "awaiting_near"))
    service.tick(sid)
    assert state.component_tests.actions == [("hc1", "near")]
    state.component_tests.runs[0]["phase"] = "awaiting_far"
    service.tick(sid)
    assert service.get(sid)["phase"] == "prepare_far"
    service.action(sid, "ready", "far-ready", context=context)
    assert state.component_tests.actions[-1] == ("hc1", "far")
    state.component_tests.runs[0].update(outcome="passed", phase="finished", reserved=False)
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_capture"


def test_tft_blind_observation_and_human_gate_then_trial(setup, monkeypatch):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context, "螢幕異常")
    service.tick(sid)
    tft_job = state.pi_execution.jobs[0]
    assert tft_job["kind"] == "test" and tft_job["component_id"] == "mrd-tf240-8p-cs"
    tft_job.update(state="running", run_id="tft1")
    state.component_tests.runs.append(_run("tft1", "mrd-tf240-8p-cs", context, "display_red"))

    class Sampler:
        def __init__(self, state, tests, run_id, **kwargs):
            self.run_id = run_id
        def start(self):
            return self
        def stop(self):
            samples = []
            for seq, phase in enumerate(("display_red", "display_lime", "display_blue", "display_code"), 1):
                stage = dict(run_id="tft1", seq=seq, phase=phase, received_monotonic_ms=100, post_display=True,
                             committed_at=1)
                meta = dict(source="device", target="tft_screen", run_id="tft1", phase_seq=seq, phase=phase,
                            phase_evidence=stage, phase_association="candidate_requires_marker",
                            runtime_revision=7, camera_id=current_debug_camera(state),
                            frame_id=seq+10, seq=seq+10, ts_ms=300,
                            quality=dict(score=1, warnings=[]), stability=dict(stable=True))
                samples.append(({"overview": b"phase" + str(seq).encode()}, meta))
            return samples

    import app.debug_capture
    monkeypatch.setattr(app.debug_capture, "TFTPhaseSampler", Sampler)
    service.tick(sid)
    state.component_tests.runs[0].update(phase="awaiting_visual", outcome="awaiting_confirmation")
    service.tick(sid)
    result = service.get(sid)
    assert result["status"] == "awaiting_visual"
    assert result["camera_verdict"] == "read_current_frame"
    assert result["test_results"][0]["outcome"] == "awaiting_confirmation"
    assert all("1234" not in prompt for prompt, _ in state.design_service.bridge.calls)
    assert all("options" not in prompt for prompt, _ in state.design_service.bridge.calls)
    assert len([e for e in result["evidence"] if e.get("test_id") == "tft1"]) == 4
    assert not any(j["kind"] == "trial" for j in state.pi_execution.jobs)
    state.component_tests.runs[0].update(phase="finished", outcome="passed", reserved=False)
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_capture"  # HC remains before trial.
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_ready"
    service.action(sid, "ready", "hc-near", context=context)
    hc_job = state.pi_execution.jobs[-1]
    hc_job.update(state="running", run_id="hc2")
    state.component_tests.runs.append(_run("hc2", "hc-sr04", context, "awaiting_near"))
    service.tick(sid)
    state.component_tests.runs[-1]["phase"] = "awaiting_far"
    service.tick(sid)
    service.action(sid, "ready", "hc-far", context=context)
    state.component_tests.runs[-1].update(phase="finished", outcome="passed", reserved=False)
    service.tick(sid)
    trial_job = state.pi_execution.jobs[-1]
    assert trial_job["kind"] == "trial", service.get(sid)
    trial_job.update(state="running", run_id="trial1")
    state.integration_trials.runs.append(dict(id="trial1", project_id=context["project"]["id"],
                                               outcome="awaiting_confirmation", phase="finished", reason=None))
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_trial_visual"
    state.integration_trials.runs[0]["outcome"] = "passed"  # human visual action on existing endpoint
    service.tick(sid)
    result = service.get(sid)
    assert result["status"] == "complete" and result["trial_result"]["outcome"] == "passed"
    assert "使用者確認" in result["report"]["confirmed"][-1]


def test_missing_tft_phases_request_cloud_guidance_before_retest(setup, monkeypatch):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context, "螢幕異常")
    service.tick(sid)
    state.pi_execution.jobs[0].update(state="running", run_id="tft1")
    state.component_tests.runs.append(_run("tft1", "mrd-tf240-8p-cs", context, "display_red"))

    class EmptySampler:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            return self
        def stop(self):
            return []

    import app.debug_capture
    monkeypatch.setattr(app.debug_capture, "TFTPhaseSampler", EmptySampler)
    service.tick(sid)
    state.component_tests.runs[0].update(phase="awaiting_visual", outcome="awaiting_confirmation")
    service.tick(sid)
    assert service.get(sid)["phase"] == "tft_retest_stop"
    assert ("tft1", "stop") in state.component_tests.actions
    service.tick(sid)
    assert len(state.pi_execution.jobs) == 1
    assert service.get(sid)["status"] == "diagnosing"
    calls_before = len(state.design_service.bridge.calls)
    original = state.design_service.bridge.generate
    def guide(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="guide_user", next_step="請靠近螢幕並避開右上角反光，再拍一張。")
        return answer
    state.design_service.bridge.generate = guide
    for _ in range(3):
        service.tick(sid)
    assert len(state.design_service.bridge.calls) == calls_before + 1
    assert service.get(sid)["instruction"] == "請靠近螢幕並避開右上角反光，再拍一張。"
    assert service.get(sid)["phase"] == "guided_observation"
    assert len(state.pi_execution.jobs) == 1


def test_stop_drops_late_observation_and_cancels_queue(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "near-ready", context=context)
    service.action(sid, "stop", "stop-1")
    assert state.pi_execution.jobs[0]["state"] == "cancelled"
    assert service.get(sid)["status"] == "stopped"
    assert service.action(sid, "stop", "stop-1")["status"] == "stopped"
    with pytest.raises(ValueError, match="invalid_phase"):
        service.action(sid, "ready", "late-ready", context=context)


def test_stop_running_fixed_test_uses_existing_stop_action(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "ready", context=context)
    state.pi_execution.jobs[0].update(state="running", run_id="hc1")
    state.component_tests.runs.append(_run("hc1", "hc-sr04", context, "awaiting_near"))
    assert service.get(sid)["run_id"] is None  # executor began before session poll
    service.action(sid, "stop", "stop-running")
    assert ("hc1", "stop") in state.component_tests.actions
    assert service.get(sid)["status"] == "stopped"


def test_stop_cancels_handoff_before_fixed_runner_launch(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "ready", context=context)
    state.pi_execution.jobs[0].update(state="stopping", run_id=None)
    service.action(sid, "stop", "stop-handoff")
    assert state.pi_execution.jobs[0]["state"] == "cancelled"
    assert not state.component_tests.runs


def test_confirmed_repair_apply_hands_off_existing_trial(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service._repair(sid, "作品行為不對")
    service.sessions[sid]["phase"] = "repair_ready"
    changed = deepcopy(context)
    changed["code"] += "\n# confirmed logic repair"
    from app.debug_support import digest
    job_id = state.pi_execution.submit("trial", changed, "repair-candidate")
    state.debug_cases.cases["case1"].update(candidate=dict(applied=True), applied_hash=digest(changed["code"]),
                                            history=[dict(job_id=job_id)])
    result = service.action(sid, "continue", "repair-continue", context=changed)
    assert result["status"] == "testing"
    assert result["binding"]["code_hash"] == digest(changed["code"])
    assert result["jobs"][0]["id"] == job_id


def test_api_contract_and_evidence_is_jpeg(setup):
    service, state = setup
    state.debug_sessions = service
    app = FastAPI()
    for key, value in vars(state).items():
        setattr(app.state, key, value)
    app.include_router(router)
    client = TestClient(app)
    context = _context()
    response = client.post("/api/debug/sessions", json=dict(context=context, symptom="距離異常", request_id="api-create"))
    assert response.status_code == 200
    sid = response.json()["id"]
    service.tick(sid)
    service.tick(sid)
    service.tick(sid)
    current = client.get(f"/api/debug/sessions/{sid}").json()
    assert current["binding"]["project_id"] == context["project"]["id"]
    assert current["evidence"]
    photo = client.get(current["evidence"][0]["url"])
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert client.get("/api/debug/sessions").json()["active"]["id"] == sid


@pytest.mark.parametrize("change", ["missing", "stale"])
def test_unconfirmed_guide_allows_cloud_photo_but_never_hardware(setup, change):
    service, state = setup
    context = _context()
    if change == "missing":
        context["guide_confirmations"] = {}
        context["test_keys"] = {}
    else:
        context["test_keys"]["hc-sr04"] = "stale-key"
    sid = _diagnosed(service, context)
    service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == "wiring_required"
    assert not result["hardware_ready"]
    assert result["hardware_blocker"].startswith("wiring_confirmation")
    assert result["observations"][0]["source"] == "codex_cloud"
    assert result["observations"][0]["model_receipt"]["capture_ids"] == [result["evidence"][0]["id"]]
    assert state.design_service.bridge.images == [[b"jpeg-1"]]
    assert not state.pi_execution.jobs
    for method in (service._queue_test, service._queue_trial):
        service.sessions[sid]["status"] = "awaiting_ready"
        method(sid)
        assert service.get(sid)["phase"] == "wiring_required"
        assert not state.pi_execution.jobs
    with pytest.raises(ValueError, match="wiring_confirmation"):
        service.authorize_case_hardware(result["case_id"])
    with pytest.raises(ValueError, match="wiring_confirmation"):
        service.authorize_context_hardware(context)


def test_cloud_receives_new_photo_pi_readings_program_and_no_tft_answer(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    state.debug_cases.cases["case1"]["evidence"]["pi"] = dict(
        program="running", invocation_id="current-invocation", logs="hidden-challenge-answer-8192",
        telemetry=dict(distance_cm=17.25, latest_valid_at=123, heartbeat_at=124),
        password="private")
    state.component_tests.runs.append(dict(id="tft-old", project_id=context["project"]["id"],
        component_id="mrd-tf240-8p-cs", outcome="failed", reason="display_black",
        challenge_code="hidden-challenge-answer-8192", options=["8192"], logs=["8192"]))
    service.tick(sid)
    prompt, args = state.design_service.bridge.calls[-1]
    payload = json.loads(prompt.split("Diagnostic evidence:\n", 1)[1])
    assert payload["telemetry"]["distance_cm"] == 17.25
    assert payload["pi"]["invocation_id"] == "current-invocation"
    assert payload["program"] == context["code"][:16000]
    assert payload["test_results"][-1]["reason"] == "display_black"
    assert "hidden-challenge-answer-8192" not in prompt and '"options"' not in prompt
    assert args["restricted_tools"] is True and args["fail_if_busy"] is True
    assert state.design_service.bridge.images[-1] == [service.evidence(sid, service.get(sid)["evidence"][-1]["id"])]


def test_cloud_inherits_selected_variant_design_and_actual_guide_progress(setup):
    service, state = setup
    context = _context()
    hc_wires = [wire for wire in context["project"]["wiring"] if wire["componentId"] == "hc-sr04"]
    del context["guide_confirmations"][hc_wires[0]["id"]]
    context["guide_confirmations"][hc_wires[1]["id"]]["signature"] = "old-wiring"
    sid = _diagnosed(service, context)
    service.tick(sid)
    prompt = state.design_service.bridge.calls[-1][0]
    payload = json.loads(prompt.split("Diagnostic evidence:\n", 1)[1])
    hc = next(spec for spec in payload["selected_component_specs"] if spec["id"] == "hc-sr04")
    pins = {pin["id"]: pin for pin in hc["electrical_pins"]}
    assert hc["selected_variant"] == "HC-SR04+ / 3.3V"
    assert hc["profile_version"] == "2.0.0"
    assert pins["VCC"]["voltage"] == 3.3 and pins["ECHO"]["signal_voltage"] == 3.3
    assert hc["profile_hash"] == context["project"]["profile_versions"]["hc-sr04"]["sha256"]
    assert payload["project"]["title"] == context["project"]["title"]
    assert payload["project"]["parameters"] == context["project"]["parameters"]
    guide = next(item for item in payload["wiring_progress"]["components"] if item["component_id"] == "hc-sr04")
    assert guide["confirmed_count"] == 2 and guide["required_count"] == 4
    assert [wire["state"] for wire in guide["wires"]] == [
        "not_confirmed", "stale_confirmation", "manually_confirmed", "manually_confirmed"]
    assert "silkscreen alone is NOT evidence" in prompt
    assert not state.pi_execution.jobs


def test_cloud_distinguishes_current_test_evidence_from_stale_or_other_pi(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    current = _run("current", "hc-sr04", context, "finished", "passed")
    invalid = {**current, "id": "invalid", "invalidated": True}
    other_pi = {**current, "id": "other-pi", "target_id": "another-pi"}
    old_wiring = {**current, "id": "old-wiring", "guide_key": "old"}
    state.component_tests.runs.extend([current, invalid, other_pi, old_wiring])
    service.tick(sid)
    payload = json.loads(state.design_service.bridge.calls[-1][0].split("Diagnostic evidence:\n", 1)[1])
    results = {run["id"]: run for run in payload["test_results"]}
    assert results["current"]["context_valid"] is True
    assert results["current"]["evidence_scope"] == "current_configuration"
    for rid in ("invalid", "other-pi", "old-wiring"):
        assert results[rid]["context_valid"] is False
        assert results[rid]["evidence_scope"] == "historical_only"
        assert results[rid]["invalid_reasons"]


def test_cloud_keeps_confirmed_hc_symptom_separate_from_missing_tft_confirmation(setup):
    service, state = setup
    context = _context()
    context["guide_confirmations"] = {wire_id: record for wire_id, record in context["guide_confirmations"].items()
                                      if wire_id.startswith("hc-sr04:")}
    context["test_keys"].pop("mrd-tf240-8p-cs")
    sid = _diagnosed(service, context, "HC-SR04+ 測不到距離")
    service.tick(sid)
    prompt = state.design_service.bridge.calls[-1][0]
    payload = json.loads(prompt.split("Diagnostic evidence:\n", 1)[1])
    progress = payload["wiring_progress"]
    assert payload["current_component"] == "hc-sr04"
    assert progress["current_component_confirmed"] is True
    assert progress["other_components_missing"] == ["mrd-tf240-8p-cs"]
    assert next(item for item in progress["components"] if item["component_id"] == "hc-sr04")["relevance"] == "current_debug_target"
    assert "use ask_user for ONE concrete question about that discrepancy" in prompt
    assert "Do not send an HC distance issue to TFT wiring completion" in prompt
    assert not state.pi_execution.jobs  # The existing all-project hardware gate still applies.


def test_followups_retain_original_problem_and_bounded_user_observations(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context, "距離一直是零")
    # Existing history is bounded, and replies are processed one at a time.
    service.sessions[sid]["user_messages"] = [dict(text=f"已完成調整 {index}", created_at=time.time()) for index in range(3)]
    for index in range(3, 8):
        text = f"已完成調整 {index}"
        service.action(sid, "message", f"message-{index}", context=context, text=text)
        service.tick(sid)
    # An idempotent retry must not duplicate the user's observation.
    service.action(sid, "message", "message-7", context=context, text="已完成調整 7")
    for _ in range(3):
        service.tick(sid)
    payload = json.loads(state.design_service.bridge.calls[-1][0].split("Diagnostic evidence:\n", 1)[1])
    assert payload["initial_symptom"] == "距離一直是零"
    assert payload["symptom"] == "已完成調整 7"
    assert [item["text"] for item in payload["user_observations"]] == [f"已完成調整 {index}" for index in range(2, 8)]


def test_model_question_waits_for_text_reply_without_recapture_or_hardware(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def question(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="ask_user", next_step="畫面中的感測器是原本選定的零件，還是剛換過？")
        return answer
    state.design_service.bridge.generate = question
    service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == "awaiting_user"
    assert result["capture_task"] is None
    with pytest.raises(ValueError, match="user_reply_required"):
        service.action(sid, "continue", "continue", context=context)
    for _ in range(3):
        service.tick(sid)
    assert len(state.design_service.bridge.calls) == 1 and not state.pi_execution.jobs
    service.action(sid, "message", "answer", context=context, text="是同一顆，沒有更換")
    for _ in range(3):
        service.tick(sid)
    assert len(state.design_service.bridge.calls) == 2
    assert "是同一顆，沒有更換" in state.design_service.bridge.calls[-1][0]


def test_identical_guided_adjustment_cannot_loop_through_more_photos(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def repeated(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="guide_user", next_step="請把感測器移近鏡頭。")
        return answer
    state.design_service.bridge.generate = repeated
    service.tick(sid)
    assert service.get(sid)["phase"] == "guided_observation"
    service.action(sid, "capture", "adjusted", context=context)
    for _ in range(3):
        service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == "awaiting_user" and result["capture_task"] is None
    assert len(state.design_service.bridge.calls) == 2
    assert len(result["evidence"]) == 2
    # The user may volunteer a current image explicitly even after a question.
    assert service.action(sid, "capture", "again", context=context)["status"] == "diagnosing"
    assert not state.pi_execution.jobs


@pytest.mark.parametrize("missing", [True, False])
def test_model_wiring_step_uses_existing_guide_instead_of_photo_request(setup, missing):
    service, state = setup
    context = _context()
    if missing:
        context["guide_confirmations"] = {}
        context["test_keys"] = {}
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def wiring(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="confirm_wiring", next_step="請到 03 完成 HC-SR04+ 的 GND 接線確認。")
        return answer
    state.design_service.bridge.generate = wiring
    service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == ("wiring_required" if missing else "awaiting_user")
    assert result["capture_task"] is None
    assert not state.pi_execution.jobs
    assert service.sessions[sid]["capture_pending"] is False
    assert service.sessions[sid]["context"]["guide_confirmations"] == context["guide_confirmations"]


def test_offline_pi_still_gets_cloud_visual_guidance_without_hardware(setup):
    service, state = setup
    context = _context()
    result = service.create(context, "螢幕全黑", request_id="offline")
    sid = result["id"]
    service.tick(sid)
    state.debug_cases.cases["case1"].update(issues=[dict(reason="connection_lost")],
        evidence=dict(environment_error="offline", pi=dict(program="unknown")))
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_capture"
    service.tick(sid)
    assert len(state.design_service.bridge.calls) == 1
    assert service.get(sid)["phase"] == "environment_blocked"
    assert not state.pi_execution.jobs


def test_followup_message_uses_fresh_cached_pi_without_new_frame_or_environment_probe(setup):
    service, state = setup
    context = _context()
    context.update(test_keys={}, guide_confirmations={})
    sid = _diagnosed(service, context)
    service.tick(sid)
    initial_frame = service.get(sid)["evidence"][-1]["frame_id"]
    state.pi_deployer.snapshot = lambda: dict(connected=True, program="stopped", telemetry=dict(distance_cm=42.5, latest_valid_at=123))
    state.debug_cases.diagnose = lambda *_: pytest.fail("text reply must not start another SSH environment diagnosis")
    result = service.action(sid, "message", "followup", context=context, text="移近後螢幕還是一樣")
    assert result["phase"] == "replying" and result["model_busy"]
    for _ in range(3):
        service.tick(sid)
    result = service.get(sid)
    assert len(state.design_service.bridge.calls) == 2
    assert result["evidence"][-1]["frame_id"] == initial_frame
    assert state.design_service.bridge.images[-1] == []
    prompt = state.design_service.bridge.calls[-1][0]
    payload = json.loads(prompt.split("Diagnostic evidence:\n", 1)[1])
    assert payload["telemetry"]["distance_cm"] == 42.5
    assert payload["pi_evidence_source"] == "current_cached_snapshot_no_new_probe"
    assert payload["historical_photo"]["id"] == result["evidence"][0]["id"]
    assert "TEXT-ONLY" in prompt and "HISTORICAL" in prompt
    assert result["messages"][-1]["capture_ids"] == []
    assert result["observations"][-1]["visibility"] == "uncertain"
    assert "移近後螢幕還是一樣" in state.design_service.bridge.calls[-1][0]
    assert not state.pi_execution.jobs


def test_capture_or_continue_during_cloud_response_cannot_queue_duplicate_analysis(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def while_observing(*args, **kwargs):
        for action in ("capture", "continue", "message"):
            with pytest.raises(ValueError, match="model_call_in_progress"):
                service.action(sid, action, "racing-" + action, context=context)
        answer = original(*args, **kwargs)
        answer.update(suggested_action="guide_user", next_step="請把感測器接頭移近鏡頭再拍照。")
        return answer
    state.design_service.bridge.generate = while_observing
    service.tick(sid)
    service.tick(sid)
    assert len(state.design_service.bridge.calls) == 1
    assert service.get(sid)["phase"] == "guided_observation"


def test_fast_effort_uses_advertised_support_thorough_preserves_requested_setting(setup):
    service, state = setup
    context = _context()
    state.design_service.bridge.models = lambda: dict(default_model="selected", models=[dict(
        id="selected", efforts=["medium", "high"], default_effort="high")])
    session = service.create(context, "距離未改變", model="selected", effort="high", request_id="mode")
    sid = session["id"]
    for _ in range(3):
        service.tick(sid)
    assert state.design_service.bridge.calls[-1][1]["effort"] == "medium"
    assert state.design_service.bridge.calls[-1][1]["model"] == "selected"
    assert service.get(sid)["requested_effort"] == "high"
    service.action(sid, "message", "thorough", context=context, text="為什麼？", response_mode="thorough")
    service.tick(sid)
    assert state.design_service.bridge.calls[-1][1]["effort"] == "high"
    assert service.get(sid)["response_mode"] == "thorough"
    assert service.get(sid)["messages"][-1]["effort"] == "high"


@pytest.mark.parametrize("phase", ["prepare_near", "prepare_far"])
def test_conversation_preserves_hc_preparation_and_never_starts_hardware(setup, phase):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.sessions[sid].update(status="awaiting_ready", phase=phase, instruction="準備好後按準備好了")
    service.action(sid, "message", "explain", context=context, text="目標要放多遠？")
    assert service.get(sid)["phase"] == "replying"
    service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == phase and result["status"] == "awaiting_ready"
    assert not state.pi_execution.jobs
    assert len(result["evidence"]) == 1
    assert len(result["messages"]) == 4


def test_text_reply_receipt_clock_stop_and_idempotency(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    original = state.design_service.bridge.generate
    def stop_inflight(*args, **kwargs):
        public = service.get(sid)
        assert public["model_started_at"] > 0 and public["model_capture_ids"] == []
        assert public["model_busy"]
        service.action(sid, "stop", "stop-chat")
        return original(*args, **kwargs)
    state.design_service.bridge.generate = stop_inflight
    service.action(sid, "message", "one", context=context, text="已經調整好了")
    service.action(sid, "message", "one", context=context, text="已經調整好了")
    assert sum(item["role"] == "user" for item in service.get(sid)["messages"]) == 2
    service.tick(sid)
    result = service.get(sid)
    assert result["status"] == "stopped" and result["model_started_at"] is None
    assert result["model_elapsed_ms"] >= 0
    assert len(result["observations"]) == 1
    assert len(result["messages"]) == 3  # Stopped reply cannot be appended.


def test_cloud_overview_is_bounded_derivative_tft_original_and_evidence_unchanged(setup):
    import cv2
    import numpy as np
    service, state = setup
    sid = _diagnosed(service, _context())
    _, encoded = cv2.imencode(".jpg", np.zeros((2160, 3840, 3), dtype=np.uint8))
    original_bytes = encoded.tobytes()
    entry = service._capture(sid, "hc_target")
    service.images[sid][entry["id"]] = original_bytes
    service._ask(sid, "Component: hc-sr04.", {"required": []}, [entry])
    supplied = state.design_service.bridge.images[-1][0]
    frame = cv2.imdecode(np.frombuffer(supplied, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert frame.shape[:2] == (1080, 1920)
    assert service.evidence(sid, entry["id"]) == original_bytes
    receipt = service.sessions[sid]["last_model_receipt"]
    assert receipt["image_inputs"][0]["resized"] is True
    assert service._cloud_photo(original_bytes, dict(test_id="tft1", phase="display_code")) == original_bytes


def test_transcript_is_sanitized_persisted_and_restart_does_not_replay(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context, "private 距離不變")
    service.tick(sid)
    stored = json.loads(service.store.read_text(encoding="utf-8"))[sid]
    assert stored["messages"][0]["role"] == "user"
    assert "private" not in stored["messages"][0]["text"]
    assert stored["messages"][1]["capture_ids"]
    restarted = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    result = restarted.get(sid)
    assert result["phase"] == "backend_restarted"
    assert result["messages"] == stored["messages"]
    assert all(not entry["available"] for entry in result["evidence"])


def test_conversation_counts_toward_six_call_limit_and_sanitizes_messages(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    for index in range(7):
        service.action(sid, "message", f"chat-{index}", context=context, text=f"private 已完成調整 {index}")
        service.tick(sid)
    result = service.get(sid)
    assert len(state.design_service.bridge.calls) == 6
    assert result["phase"] == "model_limit" and result["status"] == "paused"
    assert result["budget"]["model_calls"] == 6
    assert "private" not in state.design_service.bridge.calls[-1][0]
    assert not result["evidence"] and not state.pi_execution.jobs


@pytest.mark.parametrize("action", ["capture", "continue"])
def test_guided_followup_refreshes_pi_evidence_before_new_photo(setup, action):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def guide(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="guide_user", next_step="請移動目標物後再拍照。")
        return answer
    state.design_service.bridge.generate = guide
    service.tick(sid)
    original_diagnose = state.debug_cases.diagnose
    def fresh_diagnose(*args, **kwargs):
        case = original_diagnose(*args, **kwargs)
        state.debug_cases.cases[case["id"]]["evidence"]["pi"]["telemetry"] = dict(distance_cm=42.5)
        return case
    state.debug_cases.diagnose = fresh_diagnose
    result = service.action(sid, action, "fresh-" + action, context=context)
    assert result["status"] == "diagnosing"
    for _ in range(3):
        service.tick(sid)
    assert len(state.design_service.bridge.calls) == 2
    payload = json.loads(state.design_service.bridge.calls[-1][0].split("Diagnostic evidence:\n", 1)[1])
    assert payload["telemetry"]["distance_cm"] == 42.5
    assert service.get(sid)["evidence"][-1]["frame_id"] == 2


def test_unavailable_model_test_suggestion_never_executes_a_different_component(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.sessions[sid]["budget"]["tests"]["mrd-tf240-8p-cs"] = 1
    original = state.design_service.bridge.generate
    def other_test(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer["suggested_action"] = "test_tft"
        return answer
    state.design_service.bridge.generate = other_test
    service.tick(sid)
    assert service.get(sid)["phase"] == "capture_needed"
    assert service.get(sid)["error"] == "proposed_test_unavailable"
    assert not state.pi_execution.jobs


def test_failed_hc_test_refreshes_cloud_evidence_before_any_repeat(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "ready", context=context)
    state.pi_execution.jobs[0].update(state="finished", run_id="hc-failed")
    run = _run("hc-failed", "hc-sr04", context, "finished", "failed")
    run.update(reason="no_echo", samples={"near": [None, None]}, reserved=False)
    state.component_tests.runs.append(run)
    service.tick(sid)
    assert service.get(sid)["status"] == "diagnosing"
    assert len(state.pi_execution.jobs) == 1
    original = state.design_service.bridge.generate
    def guide(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(suggested_action="guide_user", next_step="請把平整物體對準兩個圓孔，重新拍照讓我確認位置。")
        return answer
    state.design_service.bridge.generate = guide
    for _ in range(3):
        service.tick(sid)
    prompt = state.design_service.bridge.calls[-1][0]
    assert '"no_echo"' in prompt and '"near": [null, null]' in prompt
    assert len(state.design_service.bridge.calls) == 2
    assert len(state.pi_execution.jobs) == 1
    assert service.get(sid)["phase"] == "guided_observation"


def test_manual_endpoints_cannot_bypass_linked_session_wiring_gate(setup):
    from app.api.debug import router as debug_router
    service, state = setup
    context = _context()
    context.update(test_keys={}, guide_confirmations={})
    sid = _diagnosed(service, context)
    state.debug_cases.pi = state.pi_deployer
    app = FastAPI()
    app.include_router(debug_router)
    app.state.debug_sessions = service
    app.state.debug_cases = state.debug_cases
    app.state.integration_trials = state.integration_trials
    app.state.pi_execution = state.pi_execution
    client = TestClient(app)
    result = client.post(f"/api/debug/cases/{service.get(sid)['case_id']}/actions", json=dict(
        action="apply", context=context, confirmed=True, candidate_id="candidate"))
    assert result.status_code == 409
    assert "wiring_confirmation_required" in result.text
    result = client.post("/api/debug/trials", json=dict(context=context, request_id="trial"))
    assert result.status_code == 409
    assert not state.pi_execution.jobs


@pytest.mark.parametrize("change", ["run", "phase", "source", "camera", "pi", "commit", "freshness"])
def test_rejects_foreign_or_stale_tft_stage(setup, change):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context, "螢幕黑屏")
    state.component_tests.runs.append(_run("tft1", "mrd-tf240-8p-cs", context, "display_red"))
    stage = dict(run_id="tft1", seq=1, phase="display_red", received_monotonic_ms=100,
                 post_display=True, committed_at=1)
    meta = dict(source="device", target="tft_screen", run_id="tft1", phase_seq=1, phase="display_red",
                phase_evidence=stage, phase_association="candidate_requires_marker", runtime_revision=7,
                camera_id=current_debug_camera(state), frame_id=1, seq=1, ts_ms=300,
                quality=dict(score=1), stability=dict(stable=True))
    if change == "run":
        meta["run_id"] = "other"
    elif change == "phase":
        meta["phase_evidence"]["phase"] = "display_blue"
    elif change == "source":
        meta["source"] = "synthetic"
    elif change == "camera":
        meta["camera_id"] = "old-camera"
    elif change == "pi":
        state.component_tests.runs[0]["target_id"] = "other-pi"
    elif change == "commit":
        meta["phase_evidence"]["post_display"] = False
    else:
        meta["ts_ms"] = 101
    with pytest.raises(ValueError):
        service._capture(sid, "tft_screen", test_id="tft1", phase="display_red",
                         supplied=({"overview": b"jpeg"}, meta))
    assert not service.get(sid)["evidence"]


def test_context_change_and_camera_switch_cancel_owned_work(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "ready-1", context=context)
    changed = deepcopy(context)
    changed["code"] += "\n# edit"
    response = service.action(sid, "context_changed", "changed-1", context=changed)
    assert response["status"] == "awaiting_capture"
    assert response["phase"] == "awaiting_user"
    assert response["evidence"][0]["current"] is False
    assert state.pi_execution.jobs[0]["state"] == "cancelled"
    assert service.action(sid, "context_changed", "changed-1", context=changed)["status"] == "awaiting_capture"
    service.action(sid, "stop", "explicit-stop")
    fresh = service.create(changed, "new symptom", request_id="create-new")
    assert fresh["id"] != sid
    state.source.current_index = 1
    assert not service.get(fresh["id"])["camera_current"]
    service.tick(fresh["id"])
    assert service.get(fresh["id"])["status"] == "paused"


def test_camera_change_supersedes_old_create_even_with_same_request_id(setup):
    service, state = setup
    context = _context()
    old = service.create(context, "距離異常", request_id="stable-create")
    state.source.current_index = 1
    new = service.create(context, "距離異常", request_id="stable-create")
    assert new["id"] != old["id"]
    assert service.get(old["id"])["phase"] == "superseded"
    assert service.create(context, "距離異常", request_id="stable-create")["id"] == new["id"]


def test_restart_does_not_replay_pending_pi_job(setup, tmp_path):
    service, state = setup
    context = _context()
    context["code"] += "\nAPI_KEY = 'ultra-secret-sentinel-9876'"  # gitleaks:allow -- fake sentinel verifies secrets are not persisted
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "ready-1", context=context)
    assert len(state.pi_execution.jobs) == 1
    stored = service.store.read_text(encoding="utf-8")
    assert "ultra-secret-sentinel-9876" not in stored
    assert '"context"' not in stored and '"receipts"' not in stored
    restarted = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert restarted.get(sid)["status"] == "paused"
    assert restarted.get(sid)["observations"] == []
    with pytest.raises(ValueError, match="restart_requires_new_session"):
        restarted.action(sid, "continue", "resume-old", context=context)
    restarted.tick(sid)
    assert len(state.pi_execution.jobs) == 1
    assert restarted.active()["active"]["phase"] == "backend_restarted"
    with pytest.raises(ValueError, match="restart_requires_stop"):
        restarted.create(context, "距離沒有變化", request_id="after-restart")
    changed = deepcopy(context)
    changed["code"] += "\n# changed while backend restarted"
    with pytest.raises(ValueError, match="restart_requires_stop"):
        restarted.create(changed, "other problem", request_id="different-project")
    restarted.action(sid, "stop", "stop-old")
    assert state.pi_execution.jobs[0]["state"] == "cancelled"
    assert restarted.create(context, "距離沒有變化", request_id="after-restart")["id"] != sid


def test_model_timeout_and_budget_never_queue_hardware(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    def timeout(*args, **kwargs):
        raise TimeoutError("model timed out")
    state.design_service.bridge.generate = timeout
    service.tick(sid)
    assert service.get(sid)["status"] == "awaiting_capture"
    assert service.get(sid)["budget"]["model_calls"] == 1
    assert not state.pi_execution.jobs
    service.sessions[sid]["budget"]["model_calls"] = 6
    service.action(sid, "capture", "retry-1", context=context)
    service.tick(sid)
    assert service.get(sid)["phase"] == "model_limit"
    assert not state.pi_execution.jobs


def test_first_cloud_call_sees_real_frame_even_when_local_framing_is_poor(setup):
    service, state = setup
    sid = _diagnosed(service, _context())
    attempts = []

    def capture(state, target, earliest_ms=None):
        attempts.append(target)
        ready = len(attempts) > 1
        return ({"overview": b"jpeg" + str(len(attempts)).encode()},
                dict(source="device", target=target, runtime_revision=7,
                     camera_id=current_debug_camera(state), frame_id=len(attempts), seq=len(attempts),
                     ts_ms=time.monotonic()*1000, captured_at="2026-09-25T00:00:00+00:00",
                     size=[640, 480], sha256="fake",
                     quality=dict(framing_ready=ready, score=1 if ready else 0,
                                  warnings=[] if ready else ["low_edge_detail"]),
                     stability=dict(stable=ready)))

    service.capture_fn = capture
    service.tick(sid)
    result = service.get(sid)
    assert len(attempts) == 1
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["frame_id"] == 1
    assert result["evidence"][0]["quality"]["warnings"] == ["low_edge_detail"]
    assert len(state.design_service.bridge.calls) == 1
    assert result["status"] == "awaiting_ready"


def test_hardware_repair_offers_optional_analysis_and_tracks_completion(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    service._repair(sid, "零件測試未通過：no_echo")
    service.tick(sid)
    service.tick(sid)
    result = service.get(sid)
    assert result["phase"] == "repair_ready"
    assert result["diagnosis"]["case_id"] == "case1"
    assert result["budget"]["model_calls"] == 0
    assert "analysis" not in state.debug_cases.cases["case1"]
    service.action(sid, "analyse", "manual-analysis", context=context)
    assert service.get(sid)["phase"] == "repair_analysing"
    assert service.get(sid)["budget"]["model_calls"] == 1
    service.tick(sid)
    assert service.get(sid)["phase"] == "repair_ready"
    assert state.debug_cases.cases["case1"]["analysis"]["facts"] == "fake"


def test_stop_during_model_call_discards_late_answer(setup):
    service, state = setup
    context = _context()
    sid = _diagnosed(service, context)
    original = state.design_service.bridge.generate
    def interrupt(prompt, schema, **kwargs):
        service.action(sid, "stop", "interrupt")
        return original(prompt, schema, **kwargs)
    state.design_service.bridge.generate = interrupt
    service.tick(sid)
    result = service.get(sid)
    assert result["status"] == "stopped"
    assert not result["observations"] and not state.pi_execution.jobs
