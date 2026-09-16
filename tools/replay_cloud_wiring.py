"""Opt-in photo regression runner; never captures or deploys hardware.

Save a still-cached job with --capture-url. Replay only with --run, using the
saved target/model and identical images. --staged permits at most four cloud
calls; isolated/legacy modes make one. Outputs are diagnostic artifacts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--capture-url")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", default="replay")
    parser.add_argument("--staged", action="store_true", help="Independent endpoint turns and optional route turn")
    parser.add_argument("--endpoint", choices=["component", "board"], help="One isolated endpoint test")
    parser.add_argument("--photo", type=Path, help="Use one explicitly selected real endpoint photo for an isolated test")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"])
    parser.add_argument("--model", help="Explicit model for controlled comparison; never silently substitutes")
    parser.add_argument("--component-pin", help="Inspect a different supported pin in the same unchanged photo (negative test)")
    args = parser.parse_args()
    folder = args.fixture.resolve()
    if args.capture_url:
        from urllib.parse import urljoin, urlparse
        parsed = urlparse(args.capture_url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            parser.error("Capture URL must be the local BoardVision API")
        with urllib.request.urlopen(args.capture_url, timeout=10) as response:
            job = json.load(response)
        folder.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for view in job["images"]:
            name = view["name"]
            if name in {"pi_reading", "component_reading", "pi_contact", "component_contact"}:
                continue
            if name not in {"pi_overview", "pi_pins", "component_overview", "component_pins"}:
                raise ValueError("Unexpected image name")
            with urllib.request.urlopen(urljoin(args.capture_url, view["url"]), timeout=10) as response:
                data = response.read()
            (folder / f"{name}.jpg").write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (folder / "baseline.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "sha256.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
        print(f"Saved {len(hashes)} original photos to {folder}", flush=True)
    if not args.run:
        return
    if Path(args.output).name != args.output:
        parser.error("Output must be a filename stem")
    from app.cloud_wiring import CloudWiringOpinion, CloudWiringRequest, cloud_prompt, inspection_views, opinion_verdict, reconcile_opinion, resolve_wire
    from app.codex_bridge import CodexBridge
    job = json.loads((folder / "baseline.json").read_text(encoding="utf-8"))
    hashes = json.loads((folder / "sha256.json").read_text(encoding="utf-8"))
    paths = [folder / f'{name}.jpg' for name in hashes]
    for path in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[path.stem]:
            raise ValueError("Fixture photo changed")
    body = CloudWiringRequest.model_validate(job["target"])
    if args.effort:
        body = body.model_copy(update={"effort": args.effort})
    if args.model:
        body = body.model_copy(update={"model": args.model})
    if args.component_pin:
        from app.designs import wiring_for
        wire = next((w for w in wiring_for([body.component_id]) if w["componentPin"] == args.component_pin), None)
        if wire is None:
            parser.error("Pin must be a supported connection for this module")
        body = body.model_copy(update={"wire_id": wire["id"], "board_pin": wire["boardPin"],
            "component_pin": wire["componentPin"], "connection_kind": wire["connectionKind"]})
    originals = {path.stem: path.read_bytes() for path in paths}
    original_capture = {**job["capture"], "views": [v for v in job["capture"]["views"] if v["name"] in hashes]}
    images, capture = inspection_views(originals, original_capture, body.component_id)
    if args.staged or args.endpoint:
        from app.cloud_connector_inspection import contact_views, inspect_endpoint, run_inspection
        images, capture = contact_views(images, capture)
    if args.photo:
        if not args.endpoint:
            parser.error("--photo requires --endpoint")
        key = "component_reading" if args.endpoint == "component" else "pi_reading"
        images = {key: args.photo.read_bytes()}
        capture = {"isolated_photo": str(args.photo.resolve()), "sha256": hashlib.sha256(images[key]).hexdigest()}
    output_views = folder / f"{args.output}-views"
    output_views.mkdir(exist_ok=False)
    paths = []
    for name, data in images.items():
        path = output_views / f"{name}{'.png' if name.endswith(('_reading', '_contact')) else '.jpg'}"
        path.write_bytes(data)
        paths.append(path)
    (folder / f"{args.output}.capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{args.output}.request.json").write_text(body.model_dump_json(indent=2), encoding="utf-8")
    prompt = cloud_prompt(body, resolve_wire(body), capture) if not (args.staged or args.endpoint) else None
    if prompt:
        (folder / f"{args.output}.prompt.txt").write_text(prompt, encoding="utf-8")
    bridge = CodexBridge()
    try:
        print(f"Cloud regression: {body.model}, effort={body.effort}, staged={args.staged}, endpoint={args.endpoint}, {len(paths)} images", flush=True)
        if args.endpoint or args.staged:
            by_name = {p.stem: p for p in paths}
            def save_stage(stage, stages):
                print(f"Stage: {stage}", flush=True)
                (folder / f"{args.output}.stages.json").write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.endpoint:
                from app.cloud_connector_inspection import endpoint_image_names, endpoint_prompt
                (folder / f"{args.output}.prompt.txt").write_text(endpoint_prompt(body, args.endpoint, endpoint_image_names(args.endpoint, by_name), None if args.photo else capture), encoding="utf-8")
                result = inspect_endpoint(bridge, body, args.endpoint, by_name, capture=None if args.photo else capture)
                (folder / f"{args.output}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                print(result.model_dump_json(indent=2), flush=True)
            else:
                opinion, issues, stages = run_inspection(bridge, body, by_name, progress=save_stage, capture=capture)
                save_stage("completed", stages)
                (folder / f"{args.output}.checked.json").write_text(json.dumps({**opinion.model_dump(), "consistency_issues": issues,
                    "verdict": opinion_verdict(opinion, body), "electrical_verified": False}, ensure_ascii=False, indent=2), encoding="utf-8")
                print(opinion.model_dump_json(indent=2), flush=True)
            return
        result = bridge.generate(prompt, CloudWiringOpinion.model_json_schema(), model=body.model,
            effort=body.effort, image_paths=paths, timeout_s=120, fail_if_busy=True)
        opinion = CloudWiringOpinion.model_validate(result)
        (folder / f"{args.output}.json").write_text(opinion.model_dump_json(indent=2), encoding="utf-8")
        checked, issues = reconcile_opinion(opinion, body)
        (folder / f"{args.output}.checked.json").write_text(json.dumps({**checked.model_dump(),
            "consistency_issues": issues, "verdict": opinion_verdict(checked, body),
            "electrical_verified": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(opinion.model_dump_json(indent=2), flush=True)
    finally:
        # The optional localization stage creates native crops after the initial
        # manifest. Save final provenance even if a later cloud stage fails.
        (folder / f"{args.output}.capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
        bridge.close()


if __name__ == "__main__":
    main()
