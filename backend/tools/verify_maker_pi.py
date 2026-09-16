"""Opt-in live deployment verification. Backs up and restores the current program.

Run manually from backend: python -m tools.verify_maker_pi
Uses the running local API. Test programs do not touch GPIO.
"""
import hashlib
import json
import shlex
import time

import httpx

from app.config import load_config
from app.pi_deploy import PiDeployer, SERVICE


def run():
    remote = PiDeployer(load_config().pi_deploy)
    api = httpx.Client(base_url="http://127.0.0.1:8100", timeout=30)
    result = remote.connect()
    if not result["ok"]:
        raise RuntimeError(result["error"])
    original_running = result["status"]["program"] == "running"
    directory = remote.config.remote_dir
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with remote._sftp() as sftp:
        original = sftp.file(directory + "/main.py").read().decode("utf-8")
    backup = directory + "/main.before-maker-" + stamp + ".py"
    remote._run(f"cp -p -- {shlex.quote(directory + '/main.py')} {shlex.quote(backup)}")
    remote._run(f"cp -p -- {shlex.quote(directory + '/run.log')} {shlex.quote(directory + '/run.before-maker-' + stamp + '.log')}")
    print("BACKUP", backup, flush=True)

    def status():
        response = api.get("/api/pi/status")
        response.raise_for_status()
        return response.json()

    def deploy(code, project=True):
        payload = {"code": code}
        if project:
            payload["project"] = {"component_ids": ["hc-sr04"], "catalog_version": "1"}
        response = api.post("/api/pi/deploy", json=payload)
        response.raise_for_status()
        assert response.json()["ok"], response.text
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            current = status()
            if not current["busy"]:
                time.sleep(1.2)
                return status()
            time.sleep(.3)
        raise TimeoutError("Deployment did not finish")

    outcomes = {}
    try:
        assert api.post("/api/pi/connect").json()["ok"]
        def sample(label):
            return f"from time import sleep\nwhile True:\n    print('{label}', flush=True)\n    sleep(.2)\n"
        first = deploy(sample("MAKER_API_TEST_A"))
        assert first["program"] == "running" and "MAKER_API_TEST_A" in first["logs"]
        second = deploy(sample("MAKER_API_TEST_B"))
        assert second["program"] == "running" and second["pid"] != first["pid"]
        assert "MAKER_API_TEST_B" in second["logs"] and "MAKER_API_TEST_A" not in second["logs"]
        processes = remote._run("ps -u pet -o pid=,args=")
        live = [line for line in processes.splitlines() if '/.venv/bin/python -u ' + directory + '/main.py' in line]
        assert len(live) == 1, live
        outcomes["redeploy_single_instance"] = {"first_pid": first["pid"], "second_pid": second["pid"], "process_count": len(live)}
        syntax = deploy("def broken(:\n    pass\n")
        assert syntax["deployment"] == "failed" and syntax["pid"] == second["pid"] and "SyntaxError" in syntax["error"]
        outcomes["syntax_preserves_running_program"] = True
        failed = deploy("raise RuntimeError('MAKER_EXPECTED_ERROR')\n")
        assert failed["deployment"] == "succeeded" and failed["program"] == "failed"
        assert any("MAKER_EXPECTED_ERROR" in line for line in failed["logs"])
        outcomes["runtime_error_is_not_deploy_failure"] = True
        print(json.dumps(outcomes), flush=True)
    finally:
        restored = deploy(original, project=False)
        if not original_running:
            remote._run("systemctl --user stop " + SERVICE)
        with remote._sftp() as sftp:
            final = sftp.file(directory + "/main.py").read().decode("utf-8")
        assert final == original.replace("\r\n", "\n"), "Original program was not restored"
        print("RESTORED", hashlib.sha256(final.encode()).hexdigest(), restored["program"], restored["logs"][-2:], flush=True)
        remote.close()
        api.close()


if __name__ == "__main__":
    run()
