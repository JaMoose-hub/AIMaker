"""Opt-in, two-call original/mixed photo smoke for the guided wiring inventory.

Uses the production output schema, prompt text, canonicalization and comparison.
This is not a hardware test or an accuracy benchmark: no human ground truth is
provided. Each condition runs once, without retries, answer corrections or cache.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.codex_bridge import CodexBridge
from app.designs import wiring_for
from app.guided_wiring_review import (
    ROLES, ReviewOpinion, _board_pins, _canonical_candidates, _crop_pixels,
    _decode, compare_candidates,
)

PRODUCTION = ROOT / "backend/app/guided_wiring_review.py"
SOURCE = ROOT / "runs/gpio-photo-poc/diagnostic-validation-20261003-170853"
INPUT_IDS = dict(pi_side_a="pi-a", pi_side_b="pi-b", component_header="hc")
# Visually selected on the historical originals. They are NOT detector outputs,
# independently validated header crops, pin geometry, or user confirmations.
MANUAL_ROIS = dict(pi_side_a=[.22, .18, .79, .59], pi_side_b=[.47, .12, .96, .73])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_prefix(source):
    """Reuse the production instruction verbatim except historical-state truth."""
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "prompt" for t in node.targets)
                and isinstance(node.value, ast.BinOp) and isinstance(node.value.left, ast.Constant)
                and isinstance(node.value.left.value, str)
                and node.value.left.value.startswith("Inventory the visible connectors")):
            original = node.value.left.value
            old = "The user states wiring is unchanged within this round; this is not proof of strand identity. "
            if old not in original:
                raise ValueError("Production prompt historical-state adaptation requires review")
            return original.replace(old, "These are historical photos; unchanged wiring between views has not been independently confirmed. This is not proof of strand identity. ")
    raise ValueError("Production inventory prompt could not be located")


def validate_array_schemas(node):
    """Catch tuple/prefixItems output rejected by the live provider preflight."""
    if isinstance(node, dict):
        if node.get("type") == "array" and ("items" not in node or "prefixItems" in node):
            raise ValueError("Cloud array schema must declare items without prefixItems")
        for value in node.values():
            validate_array_schemas(value)
    elif isinstance(node, list):
        for value in node:
            validate_array_schemas(value)


def sources(source_dir):
    rows = json.loads((source_dir / "inputs.json").read_text(encoding="utf-8"))
    result = {}
    for row in rows:
        path = (source_dir / row["input_file"]).resolve()
        if path.parent != source_dir.resolve():
            raise ValueError("Source manifest escapes its directory")
        data = path.read_bytes()
        actual = sha(data)
        if actual != row["input_sha256"]:
            raise ValueError(f"Canonical original changed: {path.name}")
        frame = _decode(data)
        size = [frame.shape[1], frame.shape[0]]
        if size != [row["width"], row["height"]]:
            raise ValueError("Canonical source size mismatch")
        result[row["image_id"]] = dict(path=path, sha256=actual, size=size)
    if set(result) != {"pi-a", "pi-b", "hc", "tft"}:
        raise ValueError("Expected the four frozen canonical originals")
    return result


def prepare(condition, directory, frozen):
    paths, manifest, slots = [], [], {}
    for role in ROLES:
        source = frozen[INPUT_IDS[role]]
        original = source["path"].read_bytes()
        if sha(original) != source["sha256"]:
            raise ValueError("Source changed during benchmark")
        frame = _decode(original)
        size = source["size"]
        capture_id = "historical-" + source["sha256"][:16]
        slots[role] = dict(capture_id=capture_id)
        if condition == "original":
            views = [("overview", frame, None, True)]
        else:
            scale = min(1., 1080 / min(frame.shape[:2])) if role == "component_header" else min(1., 1920 / max(frame.shape[:2]))
            overview = cv2.resize(frame, (round(size[0] * scale), round(size[1] * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
            views = [("overview", overview, None, scale == 1)]
            if role in MANUAL_ROIS:
                x0, y0, x1, y1 = _crop_pixels(MANUAL_ROIS[role], size)
                views.append(("detail", frame[y0:y1, x0:x1], [x0, y0, x1, y1], True))
        for name, pixels, crop, original_pixels in views:
            target = directory / f"{role}-{name}.png"
            # Original condition preserves the exact frozen PNG bytes too.
            if condition == "original":
                target.write_bytes(original)
            elif not cv2.imwrite(str(target), pixels):
                raise ValueError("Image encode failed")
            paths.append(target)
            manifest.append(dict(role=role, view=name, capture_id=capture_id,
                source_size=size, source_sha256=source["sha256"], crop=crop,
                size=[pixels.shape[1], pixels.shape[0]], original_pixels=original_pixels))
    return paths, manifest, dict(slots=slots)


def inventories(candidates):
    result = {}
    for role in ROLES:
        items = [c for c in candidates if c["role"] == role]
        result[role] = dict(candidate_count=len(items), colors=dict(Counter(c["color"] for c in items)),
            claimed_pin_count=sum(c["pin_id"] is not None for c in items),
            unknown_pin_count=sum(c["pin_id"] is None for c in items),
            pin_color_claims=[dict(pin=c["pin_id"], physical_pin=c["physical_pin"], color=c["color"],
                visibility=c["color_visibility"], contact=c["contact"]) for c in items])
    return result


def difference(first, second):
    # Counts compare inventories; IDs/boxes never imply cross-condition identity.
    def counts(items):
        return Counter((c["role"], c["pin_id"], c["color"], c["color_visibility"], c["contact"]) for c in items)
    def rows(counter):
        return [dict(role=k[0], pin_id=k[1], color=k[2], visibility=k[3], contact=k[4], count=n)
                for k, n in sorted(counter.items(), key=lambda pair: str(pair[0]))]
    a, b = counts(first), counts(second)
    return dict(original_only_inventory_entries=rows(a-b), mixed_only_inventory_entries=rows(b-a),
                exact_inventory_multiset_equal=a == b,
                interpretation="Observation disagreement only; no strand matching or correctness score.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make exactly two cloud calls, no retries")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare inputs without starting Codex")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    if args.run == args.prepare_only:
        parser.error("Choose exactly one of --run and --prepare-only")
    out = args.out.resolve()
    if out.exists():
        parser.error("Output directory must be new; never overwrite earlier evidence")
    out.mkdir(parents=True)
    entire_start = perf_counter()
    source_bytes = PRODUCTION.read_bytes()
    prefix = prompt_prefix(source_bytes.decode("utf-8-sig"))
    schema = ReviewOpinion.model_json_schema()
    validate_array_schemas(schema)
    frozen = sources(args.source)
    board_pins = _board_pins()
    wires = wiring_for(["hc-sr04"])
    component_pins = {w["componentPin"] for w in wires}
    save(out / "sources.json", {name: {**value, "path": str(value["path"])} for name, value in frozen.items()})
    (out / "production-guided-wiring-review.snapshot.py").write_bytes(source_bytes)
    save(out / "schema.json", schema)
    save(out / "expected-wiring-reference.json", dict(wires=wires,
        authority="Current project catalog reference only; not verified physical wiring or voltage variant"))
    report = dict(started_at_utc=datetime.now(timezone.utc).isoformat(), model=args.model, effort="low",
        timeout_s=210, cloud_call_attempts=0, successful_cloud_calls=0, conditions={},
        schema_source="app.guided_wiring_review.ReviewOpinion",
        production_source_sha256=sha(source_bytes), script_sha256=sha(Path(__file__).read_bytes()),
        component_id="hc-sr04", tft_inference_included=False, original_hashes_checked=4,
        manual_pi_rois=MANUAL_ROIS, crop_authority="assistant manually selected; unverified",
        human_ground_truth_provided=False, quality_accepted=False, quality_status="pending_independent_ground_truth",
        original_sources_preserved=None, limitations=[
            "One run per configuration, fixed original-then-mixed order; not latency statistics.",
            "Three historical photos: two Pi sides and HC header; TFT is hash-checked but not sent.",
            "Pi crops were selected manually, not validated by an automatic detector or human ground truth.",
            "Schema, production prompt with truthful historical-state sentence, canonicalization and comparison are reused; no live review endpoint is tested.",
            "Pin/color claims and candidate counts are model observations, not accuracy, physical continuity or electrical evidence.",
            "Cloud request time includes image transport, queue, model work and response, not pure inference.",
            "Faster output does not pass the quality gate; no hardware, camera, user-confirmation or retake time included."])
    bridge = None
    try:
        if args.run:
            setup = perf_counter()
            bridge = CodexBridge()
            status = bridge.status()
            if not status.get("logged_in") or status.get("busy"):
                raise RuntimeError("Authenticated Codex unavailable or busy; no retries")
            catalog = bridge.models(refresh=True)
            save(out / "model-catalog.json", catalog)
            selected = next((m for m in catalog["models"] if m["id"] == args.model), None)
            if not selected or "image" not in selected["input_modalities"] or "low" not in selected["efforts"]:
                raise ValueError("Requested live model must advertise image input and low effort; no fallback")
            report["model_display_name"] = selected["name"]
            report["bridge_setup_model_catalog_ms"] = round((perf_counter()-setup)*1000, 3)
        for condition in ("original", "mixed"):
            condition_start = perf_counter()
            directory = out / condition
            directory.mkdir()
            prep_start = perf_counter()
            paths, manifest, review = prepare(condition, directory, frozen)
            prompt = prefix + json.dumps(dict(board_pins={k: v["index"] for k,v in board_pins.items()},
                component_id="hc-sr04", module_pin_labels=sorted(component_pins), requested_roles=list(ROLES),
                images_in_order=manifest), ensure_ascii=False)
            save(directory / "inputs.json", manifest)
            (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
            current = dict(photo_prepare_ms=round((perf_counter()-prep_start)*1000, 3),
                           image_count=len(paths), images=manifest)
            report["conditions"][condition] = current
            save(out / "report.json", report)
            if not args.run:
                continue
            print(json.dumps(dict(stage="cloud_start", condition=condition, model=args.model, effort="low", images=len(paths))), flush=True)
            meta = {}
            cloud_start = perf_counter()
            report["cloud_call_attempts"] += 1
            try:
                raw = bridge.generate(prompt, schema, model=args.model, effort="low", image_paths=paths,
                                      timeout_s=210, fail_if_busy=True, response_metadata=meta)
            finally:
                current["cloud_request_ms"] = round((perf_counter()-cloud_start)*1000, 3)
                current["cloud_transport_metadata"] = meta
                current["condition_end_to_end_ms"] = round((perf_counter()-condition_start)*1000, 3)
            save(directory / "response.json", raw)
            report["successful_cloud_calls"] += 1
            post_start = perf_counter()
            opinion = ReviewOpinion.model_validate(raw)
            candidates = _canonical_candidates(opinion, review, board_pins, component_pins)
            rows = compare_candidates(candidates, wires, board_pins)
            save(directory / "candidates.json", candidates)
            save(directory / "comparison.json", rows)
            current["inventory"] = inventories(candidates)
            current["validation_and_output_ms"] = round((perf_counter()-post_start)*1000, 3)
            current["condition_end_to_end_ms"] = round((perf_counter()-condition_start)*1000, 3)
            save(out / "report.json", report)
            print(json.dumps(dict(stage="condition_complete", condition=condition,
                cloud_ms=current["cloud_request_ms"], total_ms=current["condition_end_to_end_ms"],
                candidates={r: value["candidate_count"] for r,value in current["inventory"].items()})), flush=True)
        if args.run:
            candidate_sets = [json.loads((out/c/"candidates.json").read_text(encoding="utf-8")) for c in ("original", "mixed")]
            report["observation_disagreements"] = difference(*candidate_sets)
            a, b = [report["conditions"][c]["condition_end_to_end_ms"] for c in ("original", "mixed")]
            report["mixed_total_time_change_percent"] = round((b-a)/a*100, 2)
        report["status"] = "completed" if args.run else "prepared_without_cloud"
    except Exception as error:
        report["status"] = "failed_without_retry"
        report["error"] = str(error)
        raise
    finally:
        if bridge:
            bridge.close()
        report["original_sources_preserved"] = all(sha(s["path"].read_bytes()) == s["sha256"] for s in frozen.values())
        report["production_file_unchanged_during_run"] = sha(PRODUCTION.read_bytes()) == sha(source_bytes)
        report["experiment_total_ms_including_setup"] = round((perf_counter()-entire_start)*1000, 3)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save(out / "report.json", report)
        print(json.dumps(dict(stage="finished", status=report.get("status"), report=str(out / "report.json"),
            calls=report["cloud_call_attempts"], original_sources_preserved=report["original_sources_preserved"])), flush=True)


if __name__ == "__main__":
    main()
