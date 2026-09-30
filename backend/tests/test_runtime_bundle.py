"""Observer/runner consistency tests; all deployment I/O is in-memory fake SSH."""
import importlib.util
import json
from pathlib import Path

import pytest

from app import debug_support
from app.debug_support import build_runtime_bundle, digest
from tests.test_debugging import ManualTrials, TrialPi, ctx, launch
from tests.test_pi_deploy import RecordingPi


def test_bundle_captures_runner_once_with_the_loaded_observer(monkeypatch):
    runner_path = Path(debug_support.__file__).parent / "runtime/project_runner.py"
    disk = {"source": "# runner present at observer import\n", "reads": 0}
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path == runner_path:
            disk["reads"] += 1
            return disk["source"]
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    spec = importlib.util.spec_from_file_location("isolated_runtime_bundle", debug_support.__file__)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    first = loaded.build_runtime_bundle(ctx()["code"])
    assert first.structured and first.runner == disk["source"]
    disk["source"] = "# incompatible runner copied to disk later\n"
    second = loaded.build_runtime_bundle(ctx()["code"])
    assert second == first
    assert second.runner != disk["source"]
    assert disk["reads"] == 1, "a live backend must not reread only half its runtime bundle"


@pytest.mark.parametrize("custom", [False, True])
def test_deployment_and_trial_upload_the_same_loaded_bundle_despite_disk_changes(tmp_path, monkeypatch, custom):
    context = ctx()
    if custom:
        context["code"] = "print('custom program, no trusted instrumentation')\n"
    expected = build_runtime_bundle(context["code"])
    runner_path = Path(debug_support.__file__).parent / "runtime/project_runner.py"
    changed_runner = "raise RuntimeError('newer incompatible on-disk runner')\n"
    original_read = Path.read_text
    rereads = []

    def read(path, *args, **kwargs):
        if path == runner_path:
            rereads.append(path)
            return changed_runner
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    deployment = RecordingPi()
    deployment._deploy(context["code"])
    assert deployment.snapshot()["deployment"] == "succeeded"
    deploy_source_path = next(path for path in deployment.files if path.endswith("/observed.py"))
    deploy_directory = deploy_source_path.rsplit("/", 1)[0]

    trial_pi = TrialPi()
    trials = ManualTrials(trial_pi, tmp_path / "trials.json")
    run = launch(trials, context)
    trial_directory, _python = trials._paths(run)

    for files, directory, duration in [(deployment.files, deploy_directory, None),
                                       (trial_pi.files, trial_directory, 60)]:
        config = json.loads(files[directory + "/run-config.json"])
        assert files[directory + "/snapshot.py"] == context["code"]
        assert files[directory + "/observed.py"] == expected.source
        assert files[directory + "/runner.py"] == expected.runner
        assert files[directory + "/runner.py"] != changed_runner
        assert config["source_hash"] == digest(expected.source)
        assert config["code_hash"] == digest(context["code"])
        assert config["structured"] is (not custom)
        assert config["duration"] == duration
    assert rereads == [], "neither execution path may replace its loaded runner with current disk contents"
