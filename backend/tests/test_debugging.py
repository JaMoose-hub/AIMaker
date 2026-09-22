"""Debug acceptance uses fake SSH/Agent. It makes no physical-hardware claim."""
from copy import deepcopy
from io import BytesIO
import json
import time
from contextlib import contextmanager
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.debug import router
from app.debug_support import digest, generated_logic, identity, observed_source, repair, sanitize
from app.debugging import DebugCases, issues_for
from app.designs import demo_design
from app.integration_trials import IntegrationTrials
from app.pi_execution import PiExecution
from tests.test_component_testing import ManualTests, context as component_context
from tests.test_pi_execution import QueuePi, consent, job


class TrialPi(QueuePi):
    @contextmanager
    def _sftp(self):
        yield self

    def file(self, path, mode):
        if path not in self.files:
            raise FileNotFoundError(path)
        return BytesIO(self.files[path].encode())

    def version_evidence(self):
        return self.snapshot()


class ManualTrials(IntegrationTrials):
    def _ensure_worker(self):
        pass


class FakeAgent:
    def __init__(self):
        self.prompts = []
        self.logic = demo_design()["logic"].replace('return f"distance_cm=', 'return f"Distance: ')

    def generate(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        return dict(facts="Mock facts", possible_causes="Mock hypothesis", next_step="Test it", logic=self.logic)


def ctx():
    p = demo_design()
    p["id"] = "debug-project"
    return dict(project=p, code=p["code"], test_keys={}, entry={})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    pi = TrialPi()
    tests = ManualTests(pi, tmp_path / "components.json")
    trials = ManualTrials(pi, tmp_path / "trials.json")
    queue = PiExecution(pi, tests, trials)
    queue._ensure_worker = lambda: None
    agent = FakeAgent()
    cases = DebugCases(pi, tests, trials, queue, agent, tmp_path / "debug.json")
    cases._spawn = lambda *args: None
    return pi, tests, trials, queue, cases, agent


def diagnose(cases, context=None, case_id=None):
    rid = cases.diagnose(context or ctx(), case_id)["id"]
    cases._diagnose(cases.cases[rid])
    return cases.cases[rid]


def analyse(cases, case, context=None):
    cases.analyse(case["id"], context or ctx(), "model", "low")
    cases._analyse(case, "model", "low")
    return case["candidate"]


def launch(trials, context=None):
    assert trials.start(context or ctx())["ok"]
    run = trials._active()
    trials._tick(run)
    return run


def finish(trials, run, **overrides):
    trials.pi.raw = "LoadState=loaded\nActiveState=inactive\nExecMainStatus=0"
    data = dict(run_id=run["id"], code_hash=run["binding"]["code_hash"], phase="finished", program_ok=True,
                structured=True, sample_seq=20, display_seq=10, distances=[10,20,30],
                latest_valid_at=time.time(), last_display_at=time.time(), exit_code=0, **overrides)
    data["heartbeat_at"] = time.time()
    trials.pi.files[trials._paths(run)[0] + "/runtime.json"] = json.dumps(data)
    trials._poll(run)


def test_diagnosis_read_only_no_cloud_no_launch_and_missing_package_not_wiring(setup):
    pi, tests, trials, queue, cases, agent = setup
    pi._set(program="running", pid=42)
    pi.fail = "environment"
    case = diagnose(cases)
    assert case["issues"][0]["reason"] == "missing_dependency"
    assert case["issues"][0]["next_action"] == "prepare_environment"
    assert pi.snapshot()["program"] == "running"
    assert not pi.files and not agent.prompts and not queue.jobs
    assert not any("stop" in cmd or "start " in cmd or "install " in cmd for cmd in pi.commands)


@pytest.mark.parametrize("cid", ["hc-sr04", "mrd-tf240-8p-cs"])
def test_existing_component_result_matching_not_new_executor(setup, cid):
    pi, tests, trials, queue, cases, agent = setup
    context = ctx()
    test_context = component_context(cid)
    test_context["project_id"] = context["project"]["id"]
    tests.start(test_context)
    tests._finish(tests._active(), "passed")
    context["test_keys"][cid] = test_context["guide_key"]
    case = diagnose(cases, context)
    assert not any(i.get("component_id") == cid for i in case["issues"])
    context["test_keys"][cid] = "different-wiring"
    assert any(i["reason"] == "stale_result" for i in diagnose(cases, context)["issues"])


def test_diagnostic_rules_keep_reader_errors_distinct_and_old_version_unknown():
    c = ctx()
    evidence = dict(pi=dict(program="running", telemetry=None, logs=["distance_cm=10"]))
    assert "telemetry_unknown" in [i["reason"] for i in issues_for(evidence,c)]
    evidence["pi"]["telemetry"] = dict(reason="reader_error", heartbeat_at=time.time())
    reasons = [i["reason"] for i in issues_for(evidence,c)]
    assert "reader_error" in reasons and "no_echo" not in reasons


def test_logic_repair_preserves_hardware_parameters_and_rejects_modified_scaffold():
    c = ctx()
    c["code"] = c["code"].replace("'distance_cm': 20", "'distance_cm': 10")
    candidate = repair(c["code"], c["project"], c["project"]["logic"])
    assert candidate["code"] == c["code"]
    assert generated_logic(candidate["code"],c["project"])[2]["distance_cm"] == 10
    with pytest.raises(ValueError, match="unsupported_draft"):
        repair(c["code"].replace("'TRIG': 17", "'TRIG': 19"), c["project"], c["project"]["logic"])
    with pytest.raises(ValueError):
        repair(c["code"], c["project"], "def on_sample(readings, settings):\n    return open('/etc/passwd').read()")
    with pytest.raises(ValueError):
        repair(c["code"], c["project"], "def on_sample(readings, settings):\n    return str(10 ** 999999999)")
    with pytest.raises(ValueError,match="mutate_inputs"):
        repair(c["code"], c["project"], "def on_sample(readings, settings):\n    alias = settings\n    alias['distance_cm'] = 999\n    return 'changed'")


def test_repair_candidate_requires_confirmation_binding_and_limit(setup):
    pi, tests, trials, queue, cases, agent = setup
    case = diagnose(cases)
    candidate = analyse(cases, case)
    assert candidate and not candidate["applied"] and not queue.jobs and not pi.files
    with pytest.raises(ValueError,match="stale_candidate"):
        cases.apply(case["id"],candidate["id"],{**ctx(),"code":"print('changed')"})
    response = cases.apply(case["id"],candidate["id"],ctx())
    assert response["code"] != ctx()["code"] and queue.jobs[-1]["kind"] == "trial"
    assert not pi.files  # FIFO did not start without its worker / handoff
    with pytest.raises(ValueError,match="stale_candidate"):
        cases.apply(case["id"],candidate["id"],ctx())
    restored = cases.restore(case["id"],{**ctx(),"code":response["code"]})
    assert restored["code"] == ctx()["code"] and not pi.files
    case = diagnose(cases, ctx(), case["id"])
    analyse(cases, case)
    with pytest.raises(ValueError,match="repair_limit_reached"):
        cases.analyse(case["id"],ctx())


def test_custom_code_diagnosis_only_agent_has_no_hardware_tools(setup):
    pi, tests, trials, queue, cases, agent = setup
    context = {**ctx(), "code":"print('custom hardware')"}
    case = diagnose(cases,context)
    assert not case["eligible"]
    analyse(cases,case,context)
    assert not case["candidate"] and not pi.files
    assert '"diagnosis_only": true' in agent.prompts[-1]


def test_secrets_redacted_from_ui_copy_and_cloud(setup):
    pi, tests, trials, queue, cases, agent = setup
    pi._set(logs=["password=private-test-password", 'Authorization: Bearer abcdefsecret', 'token="supersecret"', '-----BEGIN PRIVATE KEY-----\nkeybytes\n-----END PRIVATE KEY-----'])
    case = diagnose(cases)
    analyse(cases,case)
    text = json.dumps(cases.get(case["id"])) + agent.prompts[-1]
    for secret in ["private-test-password", "abcdefsecret", "supersecret", "keybytes"]:
        assert secret not in text


def test_trial_isolated_deadline_flock_and_no_auto_pass(setup):
    pi, tests, trials, queue, cases, agent = setup
    run = launch(trials)
    assert all("/trials/" in path for path in pi.files)
    command = next(cmd for cmd in pi.commands if cmd.startswith("systemd-run"))
    assert "RuntimeMaxSec=65" in command and "hardware.lock" in command and "--no-fork" in command
    assert "KillMode=control-group" in command
    assert json.loads(pi.files[trials._paths(run)[0]+"/run-config.json"])["duration"] == 60
    assert not trials.start(ctx())["ok"]
    finish(trials,run)
    assert run["outcome"] == "awaiting_confirmation" and not run["reserved"]
    assert not pi._test_reserved
    trials.action(run["id"],"visual",ctx(),True)
    assert run["outcome"] == "passed"


@pytest.mark.parametrize("change", ["code", "project", "profile", "wiring", "rewired", "latest"])
def test_trial_rejects_stale_confirmation(setup,change):
    pi, tests, trials, queue, cases, agent = setup
    run = launch(trials)
    finish(trials,run)
    context = ctx()
    if change == "code": context["code"] += "\n# changed"
    elif change == "project": context["project"]["id"] = "other"
    elif change == "profile": context["project"]["profile_versions"] = {}
    elif change == "wiring": context["project"]["wiring"] = []
    elif change == "rewired": context["test_keys"] = {"hc-sr04":"reconfirmed"}
    else: trials.start(ctx())
    with pytest.raises(ValueError, match="stale_trial"):
        trials.action(run["id"],"visual",context,True)


@pytest.mark.parametrize("field,value", [("structured",False),("sample_seq",0),("display_seq",0),("distances",[15,15])])
def test_trial_insufficient_data_not_hardware_pass(setup,field,value):
    pi, tests, trials, queue, cases, agent = setup
    run = launch(trials)
    finish(trials,run)
    run["evidence"][field] = value
    trials.action(run["id"],"visual",ctx(),True)
    assert run["outcome"] == "inconclusive"


def test_trial_disconnect_retains_control_restart_reconciles_no_replay(setup):
    pi, tests, trials, queue, cases, agent = setup
    run = launch(trials)
    pi.fail = "offline"
    with pytest.raises(EOFError): trials._tick(run)
    assert run["reserved"] and pi._test_reserved
    restored = ManualTrials(pi,trials.store)
    assert restored._active()["id"] == run["id"]
    assert restored._active()["phase"] == "reconnecting"
    assert PiExecution(pi,tests,restored).snapshot()["jobs"] == []
    pi.fail = None
    restored.action(run["id"],"stop")
    restored._tick(restored._active())
    assert not restored._active() and not pi._test_reserved


def test_trial_fifo_handoff_and_multitab_duplicates(setup):
    pi, tests, trials, queue, cases, agent = setup
    pi._set(program="running",pid=41,invocation_id="original")
    first = queue.submit("trial",ctx(),"request")
    assert queue.submit("trial",ctx(),"other-tab") == first
    later = queue.submit("test",component_context())
    queue._tick()
    assert job(queue,first)["state"] == "awaiting_confirmation" and not trials.runs
    consent(queue,first); queue._tick()
    run = trials._active(); trials._tick(run)
    assert run["program_stopped"]
    queue._tick();consent(queue,later);queue._tick()
    assert run["pending"] == "stop" and not tests.runs
    trials._tick(run);queue._tick()
    assert tests._active() and not trials._active()


def test_api_no_project_diagnosis_available_apply_requires_explicit_confirmation(setup):
    pi, tests, trials, queue, cases, agent = setup
    app = FastAPI();app.include_router(router)
    app.state.debug_cases,app.state.integration_trials,app.state.pi_execution=cases,trials,queue
    with TestClient(app) as client:
        result=client.post("/api/debug/cases",json={"context":{}})
        assert result.status_code==200 and not agent.prompts
        assert client.post("/api/debug/trials",json={"context":{},"request_id":"empty"}).status_code==409
        assert client.post(f"/api/debug/cases/{result.json()['id']}/actions",json={"context":{},"action":"apply"}).status_code==409


def test_observations_only_in_known_scaffold():
    observed, trusted = observed_source(ctx()["code"])
    assert trusted and "__bv_emit('sample'" in observed and "__bv_emit('display'" in observed
    custom = "print('arbitrary program')"
    assert observed_source(custom) == (custom, False)


def test_api_errors_redact_configured_credentials(setup):
    pi, tests, trials, queue, cases, agent = setup
    app = FastAPI(); app.include_router(router)
    app.state.debug_cases = cases
    def failure(*args):
        raise ValueError("password=private-test-password token=example-sensitive-token")
    cases.get = failure
    with TestClient(app) as client:
        response = client.get("/api/debug/cases/example")
    assert response.status_code == 409
    assert "private-test-password" not in response.text
    assert "example-sensitive-token" not in response.text


@pytest.mark.parametrize("mismatch", [None, "invocation_id", "code_hash", "run_id"])
def test_formal_version_requires_exact_run_hash_and_invocation(setup, mismatch):
    from app.pi_deploy import PiDeployer
    pi, *_ = setup
    rid = "a" * 32
    pi._refresh = lambda: pi._set(invocation_id="current-invocation", program="running")
    metadata = dict(run_id=rid, code_hash="current-code")
    data = dict(**metadata, invocation_id="current-invocation")
    if mismatch:
        data[mismatch] = "old-value"
    pi.files[pi.config.remote_dir + "/deployment.json"] = json.dumps(metadata)
    pi.files[pi.config.remote_dir + f"/deployments/{rid}/runtime.json"] = json.dumps(data)
    result = PiDeployer.version_evidence(pi)
    assert bool(result["version"]) == (mismatch is None)
    assert bool(result["telemetry"]) == (mismatch is None)


def test_unknown_trial_service_never_releases_reservation(setup):
    pi, tests, trials, *_ = setup
    run = launch(trials)
    pi.raw = "LoadState=loaded\nActiveState=unknown"
    trials._poll(run)
    assert run["reserved"] and pi._test_reserved == run["id"]
    assert run["reason"] == "remote_state_unknown"
    assert not trials.start(ctx())["ok"]


@pytest.mark.parametrize("error,reason", [("AssertionError: spi_missing", "spi_missing"),
    ("AssertionError: spi_device_permission", "device_permission"),
    ("ModuleNotFoundError: No module named 'spidev'", "missing_dependency")])
def test_spi_dependencies_and_permissions_are_separate(error, reason):
    result = issues_for({"environment_error":error}, {})
    assert result[0]["reason"] == reason
    assert result[0]["next_action"] == "prepare_environment"


def test_uninstrumented_program_and_stalled_display_do_not_look_healthy():
    data = dict(structured=False, heartbeat_at=time.time(), started_at=time.time()-10)
    evidence = {"pi":{"program":"running", "telemetry":data}}
    assert "telemetry_unknown" in [i["reason"] for i in issues_for(evidence, ctx())]
    data.update(structured=True, latest_valid_at=time.time(), last_display_at=time.time()-10)
    assert "display_stalled" in [i["reason"] for i in issues_for(evidence, ctx())]
