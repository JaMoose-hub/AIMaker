"""Integration trials share the component runner's durable reservation/reconciliation."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shlex
import time
import uuid

from app.component_testing import ComponentTests
from app.debug_support import DEBUG_VERSION, digest, identity, observed_source, sanitize, validate_project


class IntegrationTrials(ComponentTests):
    def __init__(self, pi, store=None):
        super().__init__(pi, store or Path(__file__).parents[1] / "runs/integration-trials.json")

    def validate(self, context):
        runtime = validate_project(context.get("project"))
        compile(context["code"], "trial.py", "exec")
        return runtime

    def _public(self, run):
        return sanitize({k: deepcopy(v) for k, v in run.items() if k not in {"code", "project", "target", "pending"}}, self.pi.config.password.get_secret_value())

    def start(self, context):
        runtime = self.validate(context)
        with self.lock, self.pi._state_lock:
            if self.closed.is_set() or self.pi._test_reserved or self.pi._state.busy:
                return dict(ok=False, error="resource_busy")
            run = dict(id=uuid.uuid4().hex, component_id="integration", project_id=context["project"]["id"],
                       target=self.target, binding=identity(context, self.target), template_version=DEBUG_VERSION,
                       code=context["code"], project=deepcopy(context["project"]), runtime=runtime,
                       duration=60, created_at=time.time(), phase="preflight", outcome="running", reason=None,
                       reserved=True, remote_launched=False, pending=None, invalidated=False, logs=[], detail="",
                       heartbeat_at=None, latest=None, samples={}, program_stopped=False, evidence=None)
            self.runs.append(run)
            self.pi._test_reserved = run["id"]
            self._save()
        self._ensure_worker()
        return dict(ok=True, **self.snapshot(context["project"]["id"]))

    def _paths(self, run):
        root = PurePosixPath(self.pi.config.remote_dir)
        if not root.is_absolute() or root.name != "Pi_deployer":
            raise ValueError("Invalid deployment directory")
        return str(root / "trials" / run["id"]), str(root / ".venv/bin/python")

    def _unit(self, run):
        # Covered by the existing orphan-service check as well as the shared flock.
        return "boardvision-test-trial-" + run["id"] + ".service"

    def _launch(self, run):
        self.pi.assert_no_component_service()
        self.pi._refresh()
        if self.pi.snapshot()["program"] in {"running", "starting", "stopping", "unknown"}:
            raise ValueError("resource_busy")
        directory, python = self._paths(run)
        root = PurePosixPath(self.pi.config.remote_dir)
        self.pi._run(f"mkdir -p {shlex.quote(directory)} {shlex.quote(str(root / 'component-tests'))}")
        source, structured = observed_source(run["code"])
        self.pi._write(directory + "/snapshot.py", run["code"])
        self.pi._write(directory + "/observed.py", source)
        self.pi._write(directory + "/runner.py", (Path(__file__).parent / "runtime/project_runner.py").read_text(encoding="utf-8"))
        self.pi._write(directory + "/run-config.json", json.dumps(dict(run_id=run["id"], code_hash=run["binding"]["code_hash"],
            source="observed.py", source_hash=digest(source), structured=structured, duration=60)))
        if run.get("pending") == "stop":
            self._finish(run, "inconclusive", "cancelled")
            return
        self._update(run, remote_launched=True, launched_at=time.time(), phase="starting")
        self.pi._run(f"systemd-run --user --unit={self._unit(run)} --service-type=exec --property=RuntimeMaxSec=65 "
            "--property=TimeoutStopSec=5 --property=KillMode=control-group --property=Restart=no "
            f"--property=WorkingDirectory={shlex.quote(directory)} /usr/bin/flock --nonblock --no-fork "
            f"{shlex.quote(str(root / 'component-tests/hardware.lock'))} {shlex.quote(python)} -u "
            f"{shlex.quote(directory + '/runner.py')} {shlex.quote(directory)}")

    def _poll(self, run):
        directory, python = self._paths(run)
        command = f"systemctl --user show {self._unit(run)} --no-pager --property=LoadState,ActiveState,ExecMainStatus,Result"
        probe = (f"import subprocess,sys; p=subprocess.run({command!r}.split(),capture_output=True,text=True,timeout=10); "
                 "print(p.stdout,end=''); absent='LoadState=not-found' in p.stdout and 'ActiveState=inactive' in p.stdout; sys.exit(0 if absent else p.returncode)")
        raw = self.pi._run(f"{shlex.quote(python)} -c {shlex.quote(probe)}")
        props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        with self.pi._sftp() as sftp:
            try:
                with sftp.file(directory + "/runtime.json", "rb") as source:
                    data = json.loads(source.read(30000).decode())
            except FileNotFoundError:
                data = None
        if data and (data.get("run_id") != run["id"] or data.get("code_hash") != run["binding"]["code_hash"]):
            data = None
        if data:
            self._update(run, evidence=sanitize(data, self.pi.config.password.get_secret_value()), heartbeat_at=data.get("heartbeat_at"))
        if props.get("ActiveState") in {"active", "activating", "deactivating"}:
            reason = "no_progress" if time.time() - (run.get("heartbeat_at") or run["launched_at"]) > 5 else None
            self._update(run, phase="running", outcome="running", reason=reason)
            return
        if props.get("ActiveState") not in {"inactive", "failed"}:
            self._update(run, outcome="inconclusive", reason="remote_state_unknown")
            return
        journal = self.pi._run(f"journalctl --user -u {self._unit(run)} -n 40 --no-pager -o cat")
        self._update(run, detail=sanitize(journal, self.pi.config.password.get_secret_value()), exit_code=int(props.get("ExecMainStatus", 0)))
        if run.get("pending") == "stop":
            self._finish(run, "inconclusive", "cancelled")
        elif not data or data.get("phase") != "finished":
            self._finish(run, "inconclusive", "timeout" if props.get("Result") == "timeout" else "no_result")
        elif not data.get("program_ok"):
            self._finish(run, "failed", data.get("reason") or "program_error")
        else:
            self._finish(run, "awaiting_confirmation", "visual_required")

    def _tick(self, run):
        with self.pi._io_lock:
            self.pi._open()
            self.pi._set(connected=True, connection_error=None)
            if run.get("pending") == "stop":
                if run["remote_launched"]:
                    self.pi._run(f"systemctl --user stop {self._unit(run)}")
                    self._poll(run)
                else:
                    self._finish(run, "inconclusive", "cancelled")
            elif not run["remote_launched"]:
                self._launch(run)
            else:
                self._poll(run)

    def action(self, rid, action, context=None, observed=False):
        with self.lock:
            run = next((r for r in self.runs if r["id"] == rid and r["target"] == self.target), None)
            if not run:
                raise ValueError("trial_not_found")
            if action == "stop":
                if run["reserved"]:
                    self._update(run, pending="stop")
                self._ensure_worker()
                return self.snapshot(run["project_id"])
            if action != "visual" or run["reserved"] or run["outcome"] != "awaiting_confirmation":
                raise ValueError("invalid_phase")
            if run["binding"] != identity(context or {}, self.target) or run is not self.runs[-1]:
                raise ValueError("stale_trial")
            data = run.get("evidence") or {}
            ids = run["project"]["component_ids"]
            distances = data.get("distances", [])
            ended = data.get("finished_at") or data.get("heartbeat_at", 0)
            sensor = "hc-sr04" not in ids or (data.get("sample_seq", 0) >= 5 and distances and max(distances)-min(distances) >= 5
                and 0 <= ended - (data.get("latest_valid_at") or 0) <= 5)
            display = "mrd-tf240-8p-cs" not in ids or (data.get("display_seq", 0) > 0 and
                ("hc-sr04" not in ids or 0 <= ended - (data.get("last_display_at") or 0) <= 5))
            passed = bool(observed and data.get("structured") and data.get("program_ok") and sensor and display)
            self._update(run, outcome="passed" if passed else "inconclusive", reason=None if passed else "insufficient_evidence",
                         visual_confirmed=observed, confirmed_at=time.time())
            return self.snapshot(run["project_id"])
