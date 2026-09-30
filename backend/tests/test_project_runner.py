"""Portable unit tests of telemetry/cleanup; systemd deadlines are asserted separately."""
import json
import importlib.util
from pathlib import Path
import time
from types import SimpleNamespace
import pytest
from app.debug_support import digest
spec = importlib.util.spec_from_file_location("project_runner", Path(__file__).parents[1] / "app/runtime/project_runner.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def prepare(tmp_path, monkeypatch, code="print('mock')", structured=True):
    (tmp_path / "observed.py").write_bytes(code.encode("utf-8"))
    (tmp_path / "run-config.json").write_text(json.dumps(dict(run_id="this-run",code_hash="original-hash",source_hash=digest(code),source="observed.py",duration=60,structured=structured)))
    callbacks,timers={},[]
    monkeypatch.setattr(runtime.signal,"SIGALRM",14,raising=False)
    monkeypatch.setattr(runtime.signal,"ITIMER_REAL",0,raising=False)
    monkeypatch.setattr(runtime.signal,"signal",lambda signal,fn:callbacks.__setitem__(signal,fn))
    monkeypatch.setattr(runtime.signal,"setitimer",lambda timer,seconds:timers.append(seconds),raising=False)
    monkeypatch.setattr(runtime.threading,"excepthook",runtime.threading.excepthook)
    return callbacks,timers


def test_heartbeat_distinct_fresh_samples_display_and_deadline(tmp_path,monkeypatch):
    callbacks,timers=prepare(tmp_path,monkeypatch)
    def run(_path,**kwargs):
        emit=kwargs["init_globals"]["_bv_emit"]
        now=time.monotonic()
        emit("sample",(now-10,.5))  # old sensor data is rejected
        emit("sample",(now,.2))
        emit("sample",(now,.2))     # duplicate timestamp is rejected
        emit("sample",(now+.001,None))
        emit("display",None)
        callbacks[runtime.signal.SIGALRM](runtime.signal.SIGALRM,None)
    monkeypatch.setattr(runtime.runpy,"run_path",run)
    assert runtime.main(str(tmp_path))==0
    data=json.loads((tmp_path/"runtime.json").read_text())
    assert timers==[60,0] and data["reason"]=="limit_reached"
    assert data["sample_seq"]==1 and data["display_seq"]==1
    assert data["distance_cm"]==80 and data["phase"]=="finished"
    assert data["code_hash"]=="original-hash" and data["run_id"]=="this-run"
    assert data["program_ok"] and "outcome" not in data  # never an automatic hardware pass


def test_reader_error_not_no_echo_and_custom_code_does_not_gain_structured_evidence(tmp_path,monkeypatch,capsys):
    prepare(tmp_path,monkeypatch,structured=False)
    def run(_path,**kwargs):
        error=RuntimeError("reader failed")
        runtime.threading.excepthook(SimpleNamespace(exc_type=RuntimeError,exc_value=error,exc_traceback=None))
    monkeypatch.setattr(runtime.runpy,"run_path",run)
    assert runtime.main(str(tmp_path))==1
    data=json.loads((tmp_path/"runtime.json").read_text())
    assert data["reason"]=="reader_error" and not data["program_ok"] and not data["structured"]
    logged=capsys.readouterr().err
    assert "BACKGROUND READER ERROR" in logged and "RuntimeError: reader failed" in logged
    assert "KeyboardInterrupt" not in logged


def test_snapshot_tampering_rejected_before_execution(tmp_path,monkeypatch):
    prepare(tmp_path,monkeypatch)
    (tmp_path/"observed.py").write_text("changed")
    with pytest.raises(RuntimeError,match="immutable_snapshot_changed"):
        runtime.main(str(tmp_path))


@pytest.mark.parametrize("hook", ["_bv_emit", "__bv_emit"])
def test_runner_executes_current_and_legacy_instrumentation(tmp_path, monkeypatch, hook):
    # Run the real runpy path: the legacy class reference is compiled to
    # _FreshDistanceSensor__bv_emit, while the display uses __bv_emit directly.
    code = f"""from time import monotonic
class FreshDistanceSensor:
    def _read(self):
        self.latest = (monotonic(), .25)
        {hook}('sample', self.latest)
FreshDistanceSensor()._read()
{hook}('display', None)
"""
    prepare(tmp_path, monkeypatch, code=code)
    original = (tmp_path / "observed.py").read_bytes()
    assert runtime.main(str(tmp_path)) == 0
    data = json.loads((tmp_path / "runtime.json").read_text())
    assert data["sample_seq"] == 1 and data["display_seq"] == 1
    assert data["distance_cm"] == 100 and data["displayed_sample_seq"] == 1
    assert data["program_ok"] and data["reason"] is None
    assert (tmp_path / "observed.py").read_bytes() == original


def test_legacy_hooks_not_exposed_to_unstructured_source(tmp_path, monkeypatch):
    code = "assert '__bv_emit' not in globals()\nassert '_FreshDistanceSensor__bv_emit' not in globals()"
    prepare(tmp_path, monkeypatch, code=code, structured=False)
    assert runtime.main(str(tmp_path)) == 0
    data = json.loads((tmp_path / "runtime.json").read_text())
    assert not data["structured"] and data["sample_seq"] == 0 and data["display_seq"] == 0
