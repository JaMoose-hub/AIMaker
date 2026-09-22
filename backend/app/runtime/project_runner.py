"""Trusted runtime wrapper. Deadline and telemetry survive browser/SSH loss."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import threading
import time
import traceback


def main(directory):
    root = Path(directory)
    cfg = json.loads((root / "run-config.json").read_text())
    source = (root / cfg["source"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != cfg["source_hash"]:
        raise RuntimeError("immutable_snapshot_changed")
    lock = threading.RLock()
    stop = threading.Event()
    data = dict(run_id=cfg["run_id"], code_hash=cfg["code_hash"], invocation_id=os.environ.get("INVOCATION_ID", ""),
                structured=cfg["structured"], phase="running", started_at=time.time(), heartbeat_at=time.time(),
                sample_seq=0, display_seq=0, latest_valid_at=None, last_display_at=None, exit_code=None,
                program_ok=False, reason=None, distances=[])

    def save():
        with lock:
            data["heartbeat_at"] = time.time()
            pending = root / "runtime.tmp"
            pending.write_text(json.dumps(data), encoding="utf-8")
            pending.replace(root / "runtime.json")

    def emit(kind, value):
        with lock:
            if kind == "sample":
                stamp, reading = value
                if stamp > data.get("sample_stamp", float("-inf")) and reading is not None and 0 < reading < 1 and 0 <= time.monotonic() - stamp < 1:
                    data.update(sample_stamp=stamp, sample_seq=data["sample_seq"]+1, latest_valid_at=time.time(), distance_cm=round(reading*400, 1))
                    data["distances"] = (data["distances"] + [data["distance_cm"]])[-300:]
            elif kind == "display":
                data.update(display_seq=data["display_seq"]+1, last_display_at=time.time(), displayed_sample_seq=data["sample_seq"])

    def heartbeat():
        while not stop.wait(.5):
            save()

    def finish(signum, _frame):
        data["reason"] = "limit_reached" if signum == signal.SIGALRM else "stopped"
        raise SystemExit(0)

    def thread_error(args):
        data.update(reason="reader_error", detail="".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))[-4000:])
        import _thread
        _thread.interrupt_main()

    threading.excepthook = thread_error
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGALRM, finish)
    if cfg.get("duration"):
        signal.setitimer(signal.ITIMER_REAL, cfg["duration"])
    save()
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    exit_code = 0
    try:
        runpy.run_path(str(root / cfg["source"]), run_name="__main__", init_globals={"__bv_emit": emit})
    except SystemExit as error:
        exit_code = error.code if isinstance(error.code, int) else (1 if error.code else 0)
    except BaseException:
        exit_code = 1
        data.setdefault("detail", traceback.format_exc()[-4000:])
        data["reason"] = data.get("reason") or "program_error"
        traceback.print_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        stop.set()
        worker.join(2)
        data.update(phase="finished", exit_code=exit_code, program_ok=exit_code == 0 and data.get("reason") != "reader_error", finished_at=time.time())
        save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
