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
    (tmp_path / "observed.py").write_text(code)
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
        emit=kwargs["init_globals"]["__bv_emit"]
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


def test_reader_error_not_no_echo_and_custom_code_does_not_gain_structured_evidence(tmp_path,monkeypatch):
    prepare(tmp_path,monkeypatch,structured=False)
    def run(_path,**kwargs):
        error=RuntimeError("reader failed")
        runtime.threading.excepthook(SimpleNamespace(exc_type=RuntimeError,exc_value=error,exc_traceback=None))
    monkeypatch.setattr(runtime.runpy,"run_path",run)
    assert runtime.main(str(tmp_path))==1
    data=json.loads((tmp_path/"runtime.json").read_text())
    assert data["reason"]=="reader_error" and not data["program_ok"] and not data["structured"]


def test_snapshot_tampering_rejected_before_execution(tmp_path,monkeypatch):
    prepare(tmp_path,monkeypatch)
    (tmp_path/"observed.py").write_text("changed")
    with pytest.raises(RuntimeError,match="immutable_snapshot_changed"):
        runtime.main(str(tmp_path))
