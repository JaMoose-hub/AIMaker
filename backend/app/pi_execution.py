"""One FIFO for deployment and component tests; no GPIO work in request handlers.

Waiting requests are memory-only and are cancelled by a backend restart, never
replayed. Existing remote services and persisted tests are reconciled first.
"""
from copy import deepcopy
import hashlib
import json
import threading
import time
import uuid

from app.component_testing import redact
from app.designs import MODULES
from app.pi_deploy import RemoteCommandError

DONE = {"finished", "failed", "cancelled"}
LIVE_PROGRAM = {"running", "starting", "stopping"}


class PiExecution:
    def __init__(self, pi, tests, trials=None):
        self.pi, self.tests, self.trials = pi, tests, trials
        self.lock = threading.RLock()
        self.jobs = []
        self.closed = threading.Event()
        self.worker = None

    def snapshot(self):
        with self.lock:
            recent = {job["id"] for job in self.jobs[-20:]}
            return {"jobs": [{k: deepcopy(v) for k, v in job.items()
                              if k not in {"payload", "fingerprint", "request_id", "consent"}}
                             for job in self.jobs if job["state"] not in DONE or job["id"] in recent], "policy": "confirm_then_fifo"}

    def submit(self, kind, payload, request_id=None):
        payload = deepcopy(payload)
        fingerprint_payload = payload
        if kind == "trial" and self.trials:
            from app.debug_support import identity
            fingerprint_payload = identity(payload, self.trials.target)
        fingerprint = hashlib.sha256(json.dumps([kind, fingerprint_payload], sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.closed.is_set():
                raise ValueError("executor_closed")
            for job in self.jobs:
                if request_id and job["request_id"] == request_id:
                    if job["fingerprint"] != fingerprint:
                        raise ValueError("request_id_conflict")
                    return job["id"]
                if job["state"] not in DONE and job["fingerprint"] == fingerprint:
                    return job["id"]
            if sum(j["state"] not in DONE for j in self.jobs) >= 16:
                raise ValueError("queue_full")
            if kind not in {"test", "deploy", "trial"} or kind == "trial" and not self.trials:
                raise ValueError("unsupported_job")
            context = payload if kind == "test" else payload.get("project", {})
            job = dict(id=uuid.uuid4().hex, kind=kind, state="queued", created_at=time.time(),
                       label=("HC-SR04+" if context.get("component_id") == "hc-sr04" else "MRD-TFT240") if kind == "test" else "60 秒整合試跑" if kind == "trial" else "作品部署",
                       project_id=context.get("project_id", context.get("id")), component_id=context.get("component_id"),
                       guide_key=context.get("guide_key"), payload=payload, fingerprint=fingerprint,
                       request_id=request_id, consent=None, owner=None, error=None, run_id=None)
            self.jobs.append(job)
        self._ensure_worker()
        return job["id"]

    def _ensure_worker(self):
        with self.lock:
            if not self.closed.is_set() and (not self.worker or not self.worker.is_alive()):
                self.worker = threading.Thread(target=self._loop, name="pi-execution-fifo", daemon=True)
                self.worker.start()

    def action(self, job_id, action, owner=None):
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job:
                raise ValueError("job_not_found")
            if action == "confirm":
                if job["state"] != "awaiting_confirmation" or not owner or job["owner"] != owner:
                    raise ValueError("handoff_changed")
                job["consent"] = owner
            elif action == "cancel":
                if job["state"] not in {"queued", "preflight", "awaiting_confirmation", "blocked"}:
                    raise ValueError("job_already_started")
                job.update(state="cancelled", error=None)
            else:
                raise ValueError("invalid_action")
        return self.snapshot()

    def _update(self, job, **values):
        with self.lock:
            if job["state"] != "cancelled":
                job.update(values)

    def _reconcile(self):
        runs = self.tests.status()["results"] + (self.trials.status()["results"] if self.trials else [])
        state = self.pi.snapshot()
        for job in self.jobs:
            if job["state"] != "running":
                continue
            if job["kind"] in {"test", "trial"}:
                run = next((r for r in runs if r["id"] == job["run_id"]), None)
                if run and not run["reserved"]:
                    self._update(job, state="finished", result=run["outcome"])
            elif not state["busy"]:
                self._update(job, state="failed" if state["deployment"] == "failed" else "finished",
                             error=redact(state["error"] or state["connection_error"] or "", self.pi.config.password.get_secret_value()))

    def _tick(self):
        if self.closed.is_set():
            return
        self._reconcile()
        with self.lock:
            job = next((j for j in self.jobs if j["state"] not in DONE | {"running"}), None)
        if not job or self.pi.snapshot()["busy"]:
            return
        try:
            # Validate dependencies before asking to stop any working program.
            if not job.get("checked"):
                self._update(job, state="preflight")
                payload = job["payload"]
                if job["kind"] == "test":
                    self.tests.validate(payload)
                runtime = self.trials.validate(payload) if job["kind"] == "trial" else MODULES[payload["component_id"]]["runtime"] if job["kind"] == "test" else payload
                self.pi.check_environment(runtime.get("imports", ()), runtime.get("devices", ()),
                                          payload.get("code") if job["kind"] in {"deploy", "trial"} else None)
                self._update(job, checked=True)
            if job["state"] == "cancelled":
                return
            manager = self.tests
            active = manager.status()["active"]
            if not active and self.trials:
                manager = self.trials
                active = manager.status()["active"]
            if active:
                owner = "test:" + active["id"]
            else:
                # Reconnect and inspect the real service even after a transport
                # error. Unknown state never authorizes launching another task.
                with self.pi._io_lock:
                    self.pi._open()
                    self.pi._refresh()
                    self.pi.assert_no_component_service()
                state = self.pi.snapshot()
                if state["program"] == "unknown":
                    raise RuntimeError("remote_state_unknown")
                owner = ("program:" + (state.get("invocation_id") or str(state["pid"]))) if state["program"] in LIVE_PROGRAM else None
            if job["state"] == "cancelled":
                return
            if owner:
                if job.get("consent") != owner:
                    self._update(job, state="awaiting_confirmation", owner=owner, error=None)
                    return
                # Make cancellation and stop dispatch mutually exclusive. Consent
                # belongs to this exact process/run, not any future occupant.
                with self.lock:
                    if job["state"] == "cancelled":
                        return
                    job.update(state="stopping", owner=owner, error=None)
                if active:
                    if job.get("stop_sent") != owner:
                        manager.action(active["id"], "stop", "")
                        self._update(job, stop_sent=owner)
                    return  # _test_reserved stays held until remote stop is proven.
                if not self.pi.stop_program(owner):
                    self._update(job, state="queued", consent=None, checked=False)
                    return
                self._update(job, program_stopped=True)
            with self.lock:
                if self.closed.is_set() or job["state"] == "cancelled":
                    return
                if job["kind"] in {"test", "trial"}:
                    runner = self.tests if job["kind"] == "test" else self.trials
                    result = runner.start(job["payload"])
                    if result["ok"]:
                        run = result["active"]
                        job.update(run_id=run["id"], state="running", error=None)
                        if job.get("program_stopped"):
                            with runner.lock:
                                runner._update(runner._active(), program_stopped=True)
                else:
                    result = self.pi.deploy(**job["payload"])
                    if result["ok"]:
                        job.update(state="running", error=None)
                if not result["ok"]:
                    job.update(state="blocked", error=result.get("error", "resource_busy"))
        except (ValueError, SyntaxError, RemoteCommandError) as error:
            # A failed preflight can be removed from FIFO. After a stop request,
            # retain the job so the uncertain remote state is reconciled first.
            text = str(error).lower()
            reason = ("missing_dependency" if "no module" in text else "device_permission" if "permission" in text
                      else "spi_missing" if "spi_missing" in text else "resource_busy" if "active" in text
                      else "program_error")
            self._update(job, state="blocked" if job.get("stop_sent") or job["state"] == "stopping" else "failed",
                         reason=reason, error=redact(error, self.pi.config.password.get_secret_value()))
        except Exception as error:
            self.pi._failure(error)
            self._update(job, state="blocked", error=redact(error, self.pi.config.password.get_secret_value()))

    def _loop(self):
        while not self.closed.is_set():
            self._tick()
            self.closed.wait(1)

    def close(self):
        self.closed.set()
        if self.worker:
            self.worker.join(3)
