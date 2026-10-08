"""Multi-view wiring colour advice, with explicit human-owned review decisions.

The model inventories visible connectors. Local comparison never identifies a
strand from its colour, changes guide confirmations, or queues hardware work.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import tempfile
import time
from typing import Literal
from uuid import uuid4

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.debug_support import digest
from app.designs import ROOT, wiring_for
from app.photo_observations import COLOR_LABELS
from app.wiring_photo_pipeline import (ROLES, Role, ReviewConnector, ViewInventory,
    ReviewWirePath, ReviewOpinion, ROW_CAPTURE_PLAN, capture_target_row, source_target_row,
    analysis_input_key, inspect_wiring_photos, model_calls_needed)


class WiringDialogueReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=100)
    flow_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)


class WiringReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["start", "capture", "accept_photo", "crop", "analyse", "review", "changed"]
    review_id: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=1)
    component_id: str | None = Field(default=None, max_length=100)
    role: Role | None = None
    capture_id: str | None = Field(default=None, min_length=1, max_length=100)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    crop: tuple[float, float, float, float] | None = None
    wire_id: str | None = Field(default=None, max_length=150)
    decision: Literal["confirmed", "unsure", "needs_change"] | None = None
    note: str = Field(default="", max_length=1000)
    scope: Literal["component", "all"] | None = None

    @model_validator(mode="after")
    def validate_operation(self):
        if self.op != "start" and (not self.review_id or self.revision is None):
            raise ValueError("wiring_review_revision_required")
        if self.op == "start" and not self.component_id:
            raise ValueError("component_required")
        if self.op in {"capture", "crop", "accept_photo"} and not self.role:
            raise ValueError("capture_role_required")
        if self.op == "accept_photo" and (not self.capture_id or not self.sha256):
            raise ValueError("photo_identity_required")
        if self.op == "review" and (not self.wire_id or not self.decision):
            raise ValueError("human_review_required")
        if self.crop is not None:
            x0, y0, x1, y1 = self.crop
            if not all(math.isfinite(v) for v in self.crop) or not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("invalid_wiring_review_crop")
        return self


def _board_pins():
    board = json.loads((ROOT / "profiles/boards/raspberry-pi-5/board.json").read_text(encoding="utf-8"))
    pins = {p["id"]: p for p in board["pins"]}
    outline = board.get("board", {}).get("outline_mm", [])
    if len(outline) != 2:
        return pins
    # Design geometry chooses what to photograph; it never assigns an observed
    # connector to a row. Pi 5's J8 profile has two y rows beside its bottom edge.
    for header in board.get("headers", []):
        side = header.get("side")
        if side not in {"left", "right", "top", "bottom"}:
            continue
        axis = 0 if side in {"left", "right"} else 1
        edge = outline[axis] if side in {"right", "bottom"} else 0
        group = [pin for pin in pins.values() if pin.get("header") == header.get("id")]
        if not group or any(not isinstance(pin.get("pos_mm"), list) or len(pin["pos_mm"]) < 2
                            or not isinstance(pin["pos_mm"][axis], (float, int))
                            or not math.isfinite(pin["pos_mm"][axis])
                            or not 0 <= pin["pos_mm"][axis] <= outline[axis] for pin in group):
            continue
        rows = {round(pin["pos_mm"][axis], 4) for pin in group}
        if len(rows) != 2:
            continue
        near, far = sorted(rows, key=lambda value: abs(edge - value))
        if math.isclose(abs(edge - near), abs(edge - far)):
            continue
        for pin in group:
            pin["design_row"] = "outer" if round(pin["pos_mm"][axis], 4) == near else "inner"
    return pins


def _text(locale, zh, en):
    return en if locale == "en" else zh


def _new_review(component_id, *, round_number=1, review_id=None, revision=1):
    return dict(id=review_id or uuid4().hex, revision=revision, round=round_number,
                component_id=component_id, status="collecting", slots={role: None for role in ROLES},
                observations=[], terminal_observations=[], results=[], reviews={}, missing_roles=list(ROLES), no_progress_count=0,
                error=None, pending=False, last_input_key=None, analysis_revision=None,
                last_progress_key=None, model_receipt=None, elapsed_ms=None,
                analysis_started_at=None, analysis_elapsed_ms=None, photo_flow_version=2,
                capture_plan=ROW_CAPTURE_PLAN)


def _photo_label(review, role, locale="zh-TW"):
    row = capture_target_row(review, role)
    if row:
        return _text(locale, "Pi 內排（靠板中央）" if row == "inner" else "Pi 外排（靠板邊緣）",
                     "Pi inner row (toward board centre)" if row == "inner" else "Pi outer row (toward board edge)")
    return _text(locale, {"pi_side_a": "Pi 第一側", "pi_side_b": "Pi 另一側", "component_header": "零件接頭"}[role],
                 {"pi_side_a": "first Pi side", "pi_side_b": "opposite Pi side", "component_header": "module header"}[role])


def _pi_retake_text(review, role, locale, expected_pin=None):
    if capture_target_row(review, role):
        label = _photo_label(review, role, locale)
        return _text(locale, f"補拍 {label}，讓該排插頭底部與板角入鏡，避開兩排重疊。",
                     f"Retake the {label}, showing its housing bases and board corner without overlapping rows.")
    side = "另一側" if role == "pi_side_b" else "第一側"
    english = "opposite" if role == "pi_side_b" else "first"
    if expected_pin:
        return _text(locale, f"補拍 Pi {side}，保留板角方向、兩排針與 {expected_pin} 附近的插頭底部。",
                     f"Retake the {english} Pi side with the board corner, both header rows and housing bases near {expected_pin}.")
    return _text(locale, f"補拍 Pi {side}，露出板角與插頭底部。",
                 f"Retake the {english} Pi side with the board corner and housing bases visible.")


def _archive_review(session, review, reason):
    if not review.get("results") and not review.get("observations") and not review.get("terminal_observations") and not review.get("reviews"):
        return
    history = session.setdefault("wiring_review_history", [])
    history.append({**{k: deepcopy(review.get(k)) for k in
        ("id", "round", "revision", "component_id", "capture_plan", "slots", "observations", "terminal_observations", "results", "reviews", "model_receipt")},
        "reason": reason, "archived_at": datetime.now(timezone.utc).isoformat()})
    session["wiring_review_history"] = history[-24:]


def invalidate_review(session, reason):
    reviews = list(session.get("wiring_review_components", {}).values())
    if session.get("wiring_review"):
        reviews.append(session["wiring_review"])
    for review in reviews:
        if review.get("status") == "analysing" and review.get("analysis_started_at") is not None:
            review["analysis_elapsed_ms"] = max(0, round((time.time() - review["analysis_started_at"]) * 1000))
        review.update(status="stale", pending=False, error=reason, revision=review["revision"] + 1)
        for slot in review["slots"].values():
            if slot:
                slot["available"] = False
                slot.pop("photo_acceptance", None)


def photo_accepted(review, role):
    """A human selected these pixels for analysis, never confirmed a wire."""
    slot = review["slots"].get(role)
    receipt = slot.get("photo_acceptance") if slot else None
    return bool(slot and slot.get("available") and receipt and receipt.get("source") == "human"
                and receipt.get("capture_id") == slot["capture_id"]
                and receipt.get("sha256") == slot["sha256"] and receipt.get("round") == review["round"])


def saved_wiring_photos_current(session):
    """Selected immutable photographs do not depend on the live camera runtime.

    This exception is only for the three-view photo workflow, never a live
    capture or hardware test. Project/wiring bindings and original identities
    must still match, and expired/replaced evidence remains unusable.
    """
    review = session.get("wiring_review") or {}
    if (not review or not session.get("context") or session.get("phase") not in {"wiring_review", "wiring_review_analysing"}
            or review.get("status") == "stale" or not all(photo_accepted(review, role) for role in ROLES)):
        return False
    evidence = {entry["id"]: entry for entry in session.get("evidence", [])}
    binding = session.get("binding", {})
    for role in ROLES:
        slot = review["slots"][role]
        entry = evidence.get(slot["capture_id"], {})
        if (not entry.get("current") or not entry.get("available")
                or entry.get("wiring_review_id") != review.get("id") or entry.get("wiring_round") != review.get("round")
                or entry.get("sha256") != slot.get("sha256")
                or entry.get("source") == "phone_upload" and not entry.get("provenance", {}).get("asset_id")
                or any(entry.get(key) != binding.get(key) for key in ("project_id", "target_id", "code_hash", "wiring_hash"))):
            return False
    return True


def _decode(data):
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None or min(frame.shape[:2]) < 32:
        raise ValueError("wiring_review_image_invalid")
    return frame


def _crop_pixels(box, size):
    width, height = size
    x0, y0, x1, y1 = box
    pixels = [math.floor(x0 * width), math.floor(y0 * height), math.ceil(x1 * width), math.ceil(y1 * height)]
    if min(pixels[2] - pixels[0], pixels[3] - pixels[1]) < 32:
        raise ValueError("wiring_review_crop_too_small")
    return pixels


def supported_crop(metadata, role, size):
    """Reuse only independently supported, same-original header crop metadata.

    Ordinary tracking-locked/profile-projection crops do not meet this gate.
    This is deliberately not a new side-view object detector.
    """
    name = "component_pins" if role == "component_header" else "pi_pins"
    for view in metadata.get("views", []):
        support = view.get("evidence", {})
        if (view.get("name") != name or view.get("frame_id") != metadata.get("frame_id")
                or view.get("source_view", "overview") not in {"overview", "pi_overview"}
                or support.get("pin_geometry_verified") is not True
                or support.get("source_frame_id") != metadata.get("frame_id")
                or support.get("source_size") != list(size)
                or view.get("context") != "visible_header_and_wire_exit"):
            continue
        crop = view.get("crop")
        if not isinstance(crop, (list, tuple)) or len(crop) != 4:
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in crop):
            continue
        x0, y0, x1, y1 = crop
        width, height = size
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            continue
        box = [x0 / width, y0 / height, x1 / width, y1 / height]
        try:
            _crop_pixels(box, size)
        except ValueError:
            continue
        return box
    return None


def _canonical_candidates(opinion, review, board_pins, component_pins):
    by_role = {v.role: v for v in opinion.views}
    if set(by_role) != set(ROLES) or len(by_role) != len(opinion.views):
        raise ValueError("wiring_review_roles_invalid")
    output = []
    for role in ROLES:
        view, slot = by_role[role], review["slots"][role]
        ids = [c.id for c in view.connectors]
        if len(ids) != len(set(ids)):
            raise ValueError("wiring_review_duplicate_connector")
        for c in view.connectors:
            valid = component_pins if role == "component_header" else board_pins
            pin = c.pin_id if c.pin_id in valid and c.pin_evidence.strip() else None
            seat = getattr(c, "pin_seat", None)
            seat = seat.model_dump() if seat is not None else None
            if seat is not None and (role == "component_header" or seat.get("image_id") != role
                    or seat.get("capture_id") != slot["capture_id"]
                    or seat.get("source_sha256") != slot["sha256"]
                    or seat.get("source_size") != slot.get("size")):
                seat = None
                pin = None
            # A label at a neighbouring position is not an attached endpoint.
            if c.contact not in {"covers_pin", "breadboard_link"} and not (seat and c.contact != "detached"):
                pin = None
            # Older structured opinions may already name a label/housing while
            # contact remains uncertain. Preserve that observation as identity,
            # without restoring the attached endpoint or rewriting saved results.
            module_candidate = c.module_pin_id or c.pin_id
            module_evidence = c.module_pin_evidence if c.module_pin_id else c.pin_evidence
            module_pin = (module_candidate if role == "component_header"
                          and module_candidate in component_pins
                          and module_evidence.strip() and c.contact != "detached"
                          and (pin is None or module_candidate == pin) else None)
            box = c.box
            if box is not None and (not all(math.isfinite(v) for v in box)
                    or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
                box = None
            bp = board_pins.get(pin, {}) if role != "component_header" else {}
            exit_observation = review.get("exit_evidence", {}).get(f"{role}:{c.id}", {})
            if (exit_observation.get("capture_id") != slot["capture_id"]
                    or exit_observation.get("source_sha256") != slot["sha256"]):
                exit_observation = {}
            exit_observation = {k: v for k, v in exit_observation.items() if k != "capture_id"}
            output.append(dict(id=f"{role}:{c.id}", capture_id=slot["capture_id"], role=role,
                requested_row=source_target_row(review, role),
                pin_id=pin, physical_pin=bp.get("index"), pin_label=pin,
                module_pin_id=module_pin,
                module_pin_evidence=module_evidence.strip() if module_pin else "",
                color=c.wire_color.name, color_visibility=c.wire_color.visibility,
                position=c.position, evidence=c.evidence, pin_evidence=c.pin_evidence,
                contact=c.contact, box=list(box) if box else None, limitations=view.limitations,
                pin_seat=seat,
                **deepcopy(exit_observation)))
    return output


def _canonical_module_terminals(opinion, review, component_pins):
    """Keep terminal observations separate from wire exits and bind their source.

    Old free-text header notes are never parsed into terminal identity. An empty
    connector inventory therefore cannot invent an uncovered or missing pin.
    """
    views = [view for view in opinion.views if view.role == "component_header"]
    slot = (review.get("slots") or {}).get("component_header") or {}
    if (len(views) != 1 or not slot.get("capture_id") or not slot.get("sha256")
            or not slot.get("size") or slot.get("available") is False):
        return []
    output = []
    for terminal in views[0].module_terminals:
        if (terminal.capture_id != slot["capture_id"] or terminal.source_sha256 != slot["sha256"]
                or terminal.source_size != slot["size"] or not terminal.evidence.strip()):
            continue
        observed = terminal.model_dump()
        observed["pin_id"] = terminal.pin_id if terminal.pin_id in component_pins else None
        observed.update(role="component_header", source_bound=True)
        output.append(observed)
    return output


def _unconnected_terminal_advisories(candidates, wires, terminal_observations):
    """A visible uncovered expected terminal is a suspicion, never a test result."""
    current = [term for term in terminal_observations
               if term.get("role") == "component_header" and term.get("source_bound") is True
               and term.get("capture_id") and term.get("source_sha256") and term.get("source_size")
               and term.get("evidence", "").strip()]
    module = [candidate for candidate in candidates if candidate["role"] == "component_header"]
    output = {}
    for wire in wires:
        pin = wire["componentPin"]
        observations = [term for term in current if term.get("pin_id") == pin]
        if not observations or any(term.get("state") != "uncovered" for term in observations):
            continue
        # Mixed covered/uncovered terminals at different positions are valid.
        # Contradictory observations about this same position cannot accuse it.
        if any(candidate.get("contact") in {"covers_pin", "breadboard_link"}
               and (candidate.get("pin_id") or candidate.get("module_pin_id")) == pin for candidate in module):
            continue
        if any(term.get("box") and any(other.get("pin_id") not in {None, pin}
                                       and other.get("box") == term["box"] for other in current)
               for term in observations):
            continue
        # Iterate expected wires, not every visible terminal: a deliberately
        # unwired optional terminal never becomes a missing-wire accusation.
        output[wire["id"]] = deepcopy(observations[0])
    return output


def _endpoint_swap_advisories(candidates, wires, board_pins, wire_paths):
    """Find a reciprocal colour pattern, without asserting a continuous wire.

    Pi identity comes from existing grounded observations; colour never assigns
    a pin. One obscured opposite view may supplement a clear view, but two
    housings of the same colour in one view or conflicting identified positions
    defeat uniqueness. Archived independently observed pins remain usable.
    """
    board = [c for c in candidates if c["role"] != "component_header"]
    module = [c for c in candidates if c["role"] == "component_header"]
    unknown = {"unknown", "other", "multicolor"}

    def identity(candidate, is_module):
        return (candidate.get("pin_id") or candidate.get("module_pin_id")) if is_module else candidate.get("pin_id")

    def endpoint(items, pin, is_module):
        targets = [c for c in items if identity(c, is_module) == pin]
        if not targets:
            return None
        # A contradictory or detached observation is not resolved by selecting
        # whichever view has the preferred colour.
        if any(c.get("contact") == "detached" for c in targets):
            return None
        known = {c["color"] for c in targets if c["color"] not in unknown
                 and c["color_visibility"] != "not_visible"}
        if len(known) != 1:
            return None
        colour = next(iter(known))
        grounded = [c for c in targets if c["color"] == colour and c["color_visibility"] == "clear"
                    and ((c.get("module_pin_evidence") or c.get("pin_evidence", "")).strip() if is_module
                         else c.get("pin_evidence", "").strip()
                         and (c.get("contact") == "covers_pin" or c.get("pin_seat")))]
        if not grounded:
            return None
        matches = [c for c in items if c["color"] == colour and c["color_visibility"] != "not_visible"]
        if any(identity(c, is_module) not in {None, pin} for c in matches):
            return None
        # Different view IDs are not extra wires. Within a view, however,
        # multiple matches are competing housings, even when a pin is unknown.
        roles = {c["role"] for c in matches}
        if any(sum(c["role"] == role for c in matches) > 1 for role in roles):
            return None
        if any(sum(c["role"] == role for c in targets) > 1 for role in {c["role"] for c in targets}):
            return None
        return dict(color=colour, candidate=grounded[0])

    endpoints = {}
    for wire in wires:
        if (wire["connectionKind"] != "direct" or wire["boardPin"] not in board_pins
                or sum(other["boardPin"] == wire["boardPin"] for other in wires) != 1
                or sum(other["componentPin"] == wire["componentPin"] for other in wires) != 1):
            continue
        pi = endpoint(board, wire["boardPin"], False)
        component = endpoint(module, wire["componentPin"], True)
        if pi and component:
            endpoints[wire["id"]] = (wire, pi, component)
    output = {}
    for wire, pi, component in endpoints.values():
        if pi["color"] == component["color"]:
            continue  # Similar colours alone never create a passing result.
        partners = [(other, other_pi, other_module) for other, other_pi, other_module in endpoints.values()
                    if other["id"] != wire["id"] and pi["color"] == other_module["color"]
                    and component["color"] == other_pi["color"]]
        if len(partners) != 1:
            continue
        partner, partner_pi, partner_module = partners[0]
        # The existing physical-route branch retains precedence, including a
        # route that contradicts the colour hypothesis for either endpoint.
        if any(path.wire_id in {wire["id"], partner["id"]} and path.visibility == "traceable"
               and path.evidence.strip() for path in wire_paths):
            continue
        output[wire["id"]] = dict(partner=partner, board=pi, module=component,
                                   partner_board=partner_pi, partner_module=partner_module)
    return output


def _row_position_advisories(candidates, wires, board_pins, wire_paths):
    """Prioritise a two-view row discrepancy without naming a wrong pin or strand.

    The module label and unique insulation colour identify a check to make, not
    an established continuous wire. Column estimates may drift; this advisory
    uses source-bound board-centre/board-edge observations only.
    """
    module = [c for c in candidates if c["role"] == "component_header"]
    board = [c for c in candidates if c["role"] in {"pi_side_a", "pi_side_b"}]

    def source_valid(candidate):
        size = candidate.get("source_size")
        return bool(candidate.get("capture_id") and candidate.get("source_sha256")
                    and isinstance(size, (list, tuple)) and len(size) == 2
                    and all(type(value) is int and value > 0 for value in size))

    def seat_valid(candidate):
        seat = candidate.get("pin_seat") or {}
        box = seat.get("base_box")
        return bool(source_valid(candidate) and seat.get("image_id") == candidate["role"]
                    and seat.get("capture_id") == candidate["capture_id"]
                    and seat.get("source_sha256") == candidate["source_sha256"]
                    and seat.get("source_size") == candidate["source_size"]
                    and seat.get("row") in {"inner", "outer"}
                    and seat.get("orientation_anchor", "").strip()
                    and candidate.get("contact") in {"covers_pin", "uncertain"}
                    and isinstance(box, (list, tuple)) and len(box) == 4
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                    and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)

    output = {}
    for wire in wires:
        expected_row = board_pins.get(wire["boardPin"], {}).get("design_row")
        if (wire["connectionKind"] != "direct" or expected_row not in {"inner", "outer"}
                or sum(other["componentPin"] == wire["componentPin"] for other in wires) != 1
                or any(path.wire_id == wire["id"] and path.visibility == "traceable"
                       and path.evidence.strip() for path in wire_paths)):
            continue
        targets = [c for c in module if (c.get("pin_id") or c.get("module_pin_id")) == wire["componentPin"]]
        if len(targets) != 1:
            continue
        target = targets[0]
        colour = target["color"]
        if (colour in {"unknown", "other", "multicolor"} or target["color_visibility"] != "clear"
                or not source_valid(target) or target.get("contact") not in {"covers_pin", "uncertain"}
                or not (target.get("module_pin_evidence") or target.get("pin_evidence", "")).strip()
                or sum(c["color"] == colour and c["color_visibility"] != "not_visible" for c in module) != 1):
            continue
        matching = [c for c in board if c["color"] == colour and c["color_visibility"] != "not_visible"]
        if (len(matching) != 2 or {c["role"] for c in matching} != {"pi_side_a", "pi_side_b"}
                or not all(seat_valid(c) for c in matching)
                or len({c["source_sha256"] for c in matching}) != 2
                or len({c["capture_id"] for c in matching}) != 2
                or not any(c["contact"] == "covers_pin" and c["color_visibility"] == "clear" for c in matching)):
            continue
        rows = {c["pin_seat"]["row"] for c in matching}
        if len(rows) != 1 or expected_row in rows:
            continue
        # A competing colour assigned to the same observed position is a
        # contradiction, not extra evidence in favour of this hypothesis.
        if any(c.get("pin_id") and any(other["role"] == c["role"] and other is not c
                and other.get("pin_id") == c["pin_id"] and other["color"] != colour
                and other["color_visibility"] != "not_visible" for other in board) for c in matching):
            continue
        output[wire["id"]] = dict(expected_row=expected_row, candidate_row=next(iter(rows)),
                                  row_candidate_ids=[c["id"] for c in matching])
    return output


def _wire_subject(endpoint, colour, locale):
    """Name a wire using observed insulation, never a catalogue colour/anchor."""
    name = (colour or {}).get("name")
    visible = (colour or {}).get("visibility") != "not_visible"
    if visible and name in COLOR_LABELS and name not in {"unknown", "other", "multicolor"}:
        return _text(locale, f"{COLOR_LABELS[name]} {endpoint} 線", f"the {name} {endpoint} wire")
    return _text(locale, f"{endpoint} 這條線", f"the {endpoint} wire")


def _diagram_check_step(row, locale):
    subject = _wire_subject(row["expected"]["component_pin"], row.get("wire_colors", {}).get("component"), locale)
    return _text(locale, f"沿{subject}，核對接線圖中標示的應接位置。",
                 f"Trace {subject} and check the intended connection highlighted in the wiring diagram.")


def compare_candidates(candidates, wires, board_pins, locale="zh-TW", wire_paths=(), *, capture_plan=None,
                       terminal_observations=()):
    """Produce advisory colour and route findings; repeated colours never establish identity."""
    board = [c for c in candidates if c["role"] != "component_header"]
    component = [c for c in candidates if c["role"] == "component_header"]
    def module_identity(candidate):
        # Only canonical, source-bound label observations may supplement an
        # attached endpoint; this never supplies pin_id or contact authority.
        return candidate["pin_id"] or candidate.get("module_pin_id")
    def colors(items):
        return {c["color"] for c in items if c["color"] not in {"unknown", "other", "multicolor"}
                and c["color_visibility"] != "not_visible"}
    missing_terminals = _unconnected_terminal_advisories(candidates, wires, terminal_observations)
    swap_advisories = _endpoint_swap_advisories(candidates,
        [wire for wire in wires if wire["id"] not in missing_terminals], board_pins, wire_paths)
    row_advisories = _row_position_advisories(candidates,
        [wire for wire in wires if wire["id"] not in missing_terminals and wire["id"] not in swap_advisories],
        board_pins, wire_paths)
    rows = []
    for wire in wires:
        target_board = [c for c in board if c["pin_id"] == wire["boardPin"]]
        target_component = [c for c in component if module_identity(c) == wire["componentPin"]]
        bc, cc = colors(target_board), colors(target_component)
        comparison = "unknown"
        if len(bc) == len(cc) == 1:
            comparison = "similar" if bc == cc else "different"
        elif bc and cc:
            comparison = "ambiguous"
        # Several views of the same identified pin are not several wires.
        repeated = bool(cc and any(c["color"] in cc and c["pin_id"] != wire["boardPin"] for c in board))
        repeated |= bool(bc and any(c["color"] in bc and module_identity(c) != wire["componentPin"] for c in component))
        if repeated and comparison != "different":
            comparison = "ambiguous"
        chosen_board = target_board or [c for c in board if c["color"] in cc] or board
        chosen_component = target_component or [c for c in component if c["color"] in bc] or component
        # Surface duplicate-colour alternatives even when the intended pin is visible.
        if repeated:
            chosen_board = [c for c in board if c in chosen_board or c["color"] in cc]
            chosen_component = [c for c in component if c in chosen_component or c["color"] in bc]
        evidence = {
            "similar": _text(locale, "兩端可見線色相符；尚未證明是同一條線。", "Visible endpoint colours agree; strand identity is not established."),
            "different": _text(locale, "兩端可見線色不同；請核對是否有中間接線或辨色差異。", "Visible endpoint colours differ; check intermediate connections and colour interpretation."),
            "ambiguous": _text(locale, "有同色候選或互相矛盾的觀察，不能自動配對。", "Repeated-colour candidates or conflicting observations prevent a unique pairing."),
            "unknown": _text(locale, "腳位或線色尚未確認；保留可見接頭供人工核對。", "Pin identity or colour remains uncertain; visible connectors are retained for review."),
        }[comparison]
        if wire["connectionKind"] == "divider":
            evidence += _text(locale, " 此線包含分壓／中間連接，兩端可能使用不同顏色。", " This connection includes a divider/intermediate segment whose wires may differ in colour.")
        pin = board_pins.get(wire["boardPin"], {})
        def color_observation(items, values):
            if len(values) != 1:
                return dict(name="unknown", visibility="not_visible", evidence="Target pin colour is not established.")
            color = next(iter(values))
            matching = [c for c in items if c["color"] == color]
            return dict(name=color, visibility="clear" if all(c["color_visibility"] == "clear" for c in matching) else "partial",
                        evidence="; ".join(c["evidence"] for c in matching)[:500])
        row = dict(wire_id=wire["id"], expected=dict(board_pin=wire["boardPin"], physical_pin=pin.get("index"),
            bcm=int(wire["boardPin"][4:]) if wire["boardPin"].startswith("GPIO") else None,
            component_pin=wire["componentPin"], connection_kind=wire["connectionKind"]),
            pi_candidates=deepcopy(chosen_board), component_candidates=deepcopy(chosen_component),
            comparison=comparison, evidence=evidence, authority="visual_advisory",
            wire_colors=dict(board=color_observation(target_board, bc), component=color_observation(target_component, cc),
                             comparison=comparison if comparison in {"similar", "different"} else "uncertain", evidence=evidence),
            same_wire="uncertain")
        paths = [path for path in wire_paths if path.wire_id == wire["id"]]
        path = paths[0] if len(paths) == 1 else None
        observed_board = next((c for c in board if path and c["id"] == path.board_connector_id), None)
        observed_module = next((c for c in component if path and c["id"] == path.component_connector_id), None)
        # A continuous-route finding is stronger than the separate endpoint
        # colour hypothesis below. Only this branch establishes same_wire.
        supported = bool(path and path.visibility == "traceable" and path.evidence.strip()
            and observed_board and observed_module
            and observed_board["pin_id"] and observed_module["pin_id"]
            and (observed_module["pin_id"] == wire["componentPin"] or observed_board["pin_id"] == wire["boardPin"])
            and observed_board["contact"] == observed_module["contact"] == "covers_pin"
            and wire["connectionKind"] == "direct")
        diagnosis = "uncertain"
        if supported:
            diagnosis = "suspected" if (observed_board["pin_id"] != wire["boardPin"]
                or observed_module["pin_id"] != wire["componentPin"]) else "no_issue_seen"
            row["same_wire"] = "consistent"
        swap = swap_advisories.get(wire["id"]) if not supported else None
        row_advisory = row_advisories.get(wire["id"]) if not supported else None
        missing_terminal = missing_terminals.get(wire["id"])
        if missing_terminal:
            # This is a separate terminal observation, not a fabricated wire
            # exit, colour association or continuous-route finding.
            supported = False
            swap = None
            row["same_wire"] = "uncertain"
            diagnosis = "suspected"
        elif swap:
            diagnosis = "suspected"
        # One visible Pi endpoint is sufficient; absence from the opposite view
        # alone must not cause an endless request to photograph it again.
        retake_roles = []
        if diagnosis == "uncertain" and not row_advisory:
            if not target_component:
                retake_roles.append("component_header")
            elif not target_board:
                if capture_plan == ROW_CAPTURE_PLAN:
                    # Seek the expected design location, without claiming an
                    # observed wire is on that row or using a same-colour clue.
                    expected_row = board_pins.get(wire["boardPin"], {}).get("design_row")
                    retake_roles.extend({"inner": ["pi_side_a"], "outer": ["pi_side_b"]}.get(
                        expected_row, ["pi_side_a", "pi_side_b"]))
                else:
                    retake_roles.append("pi_side_b" if any(c["role"] == "pi_side_a" for c in board) else "pi_side_a")
        visible_clues = []
        if not supported:
            for label, items, targets in [((_text(locale, "零件端", "Module")), component, target_component),
                                         ((_text(locale, "Pi 端", "Pi")), board, target_board)]:
                if targets:
                    clue = next((c.get("module_pin_evidence") or c.get("pin_evidence") or c.get("evidence") for c in targets
                                 if c.get("module_pin_evidence") or c.get("pin_evidence") or c.get("evidence")), "")
                else:
                    clue = next((c.get("pin_evidence") or c.get("evidence") for c in items
                                 if c.get("contact") == "detached" and (c.get("pin_evidence") or c.get("evidence"))), "")
                    clue = clue or next((c.get("limitations") for c in items if c.get("limitations")), "")
                if clue:
                    visible_clues.append(f"{label}：{clue[:160]}")
        row["diagnosis"] = dict(status=diagnosis,
            observed_board_pin=observed_board["pin_id"] if supported else None,
            observed_physical_pin=observed_board["physical_pin"] if supported else None,
            observed_component_pin=observed_module["pin_id"] if supported else None,
            board_connector_id=observed_board["id"] if supported else None,
            component_connector_id=observed_module["id"] if supported else None,
            module_identity_known=bool(target_component),
            module_attachment_uncertain=any(c.get("module_pin_id") and c["pin_id"] is None for c in target_component),
            module_attachment_confirmed=bool(target_component) and all(
                c["pin_id"] == wire["componentPin"] and c["contact"] == "covers_pin" for c in target_component),
            evidence=path.evidence if supported else "\n".join(visible_clues) or evidence,
            retake_roles=retake_roles)
        if swap:
            partner = swap["partner"]
            partner_index = board_pins[partner["boardPin"]].get("index")
            own_colour, other_colour = swap["module"]["color"], swap["board"]["color"]
            note = _text(locale,
                f"{wire['componentPin']} 是{COLOR_LABELS.get(own_colour, own_colour)}、"
                f"{partner['componentPin']} 是{COLOR_LABELS.get(other_colour, other_colour)}；"
                "接線圖中兩個應接位置的線色相反，疑似互換，尚未沿線確認。",
                f"{wire['componentPin']} is {own_colour} and {partner['componentPin']} is {other_colour}; "
                "colours at the two intended positions in the wiring diagram are reversed. "
                "This suggests a swap; the continuous wires are not established.")
            row["diagnosis"].update(kind="reciprocal_endpoint_swap", partner_wire_id=partner["id"],
                partner_component_pin=partner["componentPin"], candidate_board_pin=partner["boardPin"],
                candidate_physical_pin=partner_index, evidence=note)
        if missing_terminal:
            row["diagnosis"].update(kind="unconnected_terminal", evidence=missing_terminal["evidence"],
                terminal_observation=missing_terminal)
        if row_advisory:
            row["diagnosis"].update(kind="row_position_check", **row_advisory,
                evidence=_text(locale,
                    "兩張 Pi 照片中的同色接頭都像在另一排，與設計接法不同；仍需沿線核對。",
                    "The same-colour housing appears on the other row in both Pi photos, unlike the design; trace the wire to check."))
        endpoint = wire["componentPin"]
        subject = _wire_subject(endpoint, row["wire_colors"]["component"], locale)
        if missing_terminal:
            row["next_step"] = _text(locale,
                f"對照接線圖，核對零件上標示 {endpoint} 的應接位置；要調整接線請先斷電。",
                f"Find the terminal labelled {endpoint} on the module and check its intended connection in the diagram; power off before changing wiring.")
        elif swap:
            other_subject = _wire_subject(partner["componentPin"], dict(name=other_colour, visibility="clear"), locale)
            row["next_step"] = _text(locale,
                f"對照接線圖，核對{subject}與{other_subject}各自的應接位置；調整前先斷電。",
                f"Check {subject} and {other_subject} against their highlighted positions in the wiring diagram; power off before changing wiring.")
        elif diagnosis == "suspected":
            row["next_step"] = _text(locale,
                f"先斷電，沿{subject}核對接線圖中標示的應接位置。",
                f"Power off, then trace {subject} and check the intended position highlighted in the wiring diagram.")
        elif row_advisory:
            row["next_step"] = _diagram_check_step(row, locale)
        elif comparison == "different":
            # This is a visible mismatch clue, not continuous-wire proof. Keep
            # the diagnosis uncertain while making the useful clue prominent.
            module_colour = row["wire_colors"]["component"]["name"]
            board_colour = row["wire_colors"]["board"]["name"]
            row["diagnosis"]["evidence"] = _text(locale,
                f"{endpoint} 零件端可見{COLOR_LABELS.get(module_colour, module_colour)}，"
                f"Pi 端候選位置可見{COLOR_LABELS.get(board_colour, board_colour)}；線色不同，兩端是否同一條線仍待核對。",
                f"The module's {endpoint} wire is {module_colour}; the candidate Pi position shows {board_colour}. "
                "The colours differ; verify whether these are the ends of the same wire.")
            row["next_step"] = _diagram_check_step(row, locale)
        elif retake_roles:
            row["next_step"] = (_text(locale,
                "Pi 排別尚未定位；補拍內排（靠板中央）與外排（靠板邊緣），保留板角與插頭底部。",
                "The Pi row is not located; photograph both inner and outer rows with board corners and housing bases.")
                if capture_plan == ROW_CAPTURE_PLAN and len(retake_roles) == 2 else _text(locale,
                f"補拍零件接頭，讓 {endpoint} 標字與插頭底部一起入鏡。",
                f"Retake the module header with the {endpoint} label and housing base visible.")
                if retake_roles[0] == "component_header" else
                _pi_retake_text({"capture_plan": capture_plan}, retake_roles[0], locale,
                                _text(locale, "接線圖標示的應接位置", "the intended position marked in the wiring diagram")))
        elif target_component and any(c["pin_id"] is None or c["contact"] != "covers_pin" for c in target_component):
            row["next_step"] = _text(locale,
                f"{endpoint} 標字與接頭位置已辨識；沿{subject}核對接線圖中標示的應接位置。",
                f"The {endpoint} label and housing position are identified; trace {subject} to the intended position highlighted in the wiring diagram.")
        else:
            row["next_step"] = _diagram_check_step(row, locale)
        rows.append(row)
    return rows


def _review_priority(row):
    finding = row.get("diagnosis", {})
    return (0 if finding.get("status") == "suspected" and finding.get("kind") == "unconnected_terminal" else
            1 if finding.get("status") == "suspected" else
            3 if finding.get("status") == "no_issue_seen" else 2,
            0 if row.get("comparison") == "different" else
            1 if finding.get("kind") == "row_position_check" else
            {"unknown": 2, "ambiguous": 3, "similar": 4}.get(row.get("comparison"), 2))


def _header_note(review, role):
    """Keep an actual view observation even when it yielded zero connectors.

    Legacy prose is quoted, never parsed into a missing-wire diagnosis. The
    caller only uses this in a completed, same-revision result; collection
    caches are not current observations. No historical round is consulted.
    """
    if role not in ROLES:
        return None
    view = next((view for view in (review.get("last_opinion") or {}).get("views", [])
                 if view.get("role") == role), {})
    observation = view.get("header_observation") or {}
    evidence = observation.get("evidence", "").strip()
    state = observation.get("state")
    if evidence and state in {"uncovered_pins", "housings_visible", "occluded", "uncertain"}:
        note = dict(state=state, evidence=evidence)
    else:
        detached = next((candidate for candidate in review.get("observations", [])
                         if candidate.get("role") == role and candidate.get("contact") == "detached"
                         and (candidate.get("pin_evidence") or candidate.get("evidence"))), None)
        if detached:
            note = dict(state="detached", evidence=detached.get("pin_evidence") or detached["evidence"])
        elif view.get("connectors") == [] and view.get("limitations", "").strip():
            note = dict(state="legacy_observation", evidence=view["limitations"].strip())
        else:
            return None
    slot = review.get("slots", {}).get(role) or {}
    source = (dict(review_id=review["id"], round=review["round"], role=role,
                   capture_id=slot["capture_id"], sha256=slot["sha256"])
              if slot.get("capture_id") and slot.get("sha256") else None)
    return dict(**note, role=role, source=source)


def _review_summary(review, pending, locale):
    """Freeze a concise photo-level summary without granting review authority.

    Several uncertain wires can share one missing view. Present that shared
    photo problem once instead of pretending the first wire is a distinct fault.
    The current per-wire decision and its guard remain separate from this view.
    """
    row = pending[0]
    diagnosis = row.get("diagnosis", {})
    counts = {status: sum(result.get("diagnosis", {}).get("status", "uncertain") == status
                          for result in review["results"])
              for status in ("suspected", "uncertain", "no_issue_seen")}
    pin = row["expected"]["component_pin"]
    role = next((role for role in diagnosis.get("retake_roles", []) if role in ROLES), None)
    both_rows = review.get("capture_plan") == ROW_CAPTURE_PLAN and set(diagnosis.get("retake_roles", [])) == {"pi_side_a", "pi_side_b"}
    if both_rows:
        role = None
    next_step = row.get("next_step", "")
    photo_note = None
    if diagnosis.get("status") == "suspected" and diagnosis.get("kind") == "unconnected_terminal":
        headline = _text(locale, f"{pin} 這個腳位疑似漏接。", f"The {pin} terminal may be unconnected.")
        role = None
    elif diagnosis.get("status") == "suspected":
        partner_pin = diagnosis.get("partner_component_pin")
        headline = (_text(locale, f"{pin} 與 {partner_pin} 疑似接反。", f"{pin} and {partner_pin} may be swapped.")
                    if diagnosis.get("kind") == "reciprocal_endpoint_swap" and partner_pin else
                    _text(locale, f"{pin} 疑似接錯，先核對這條線。", f"Check {pin}: it may be miswired."))
        role = None
    elif diagnosis.get("status") == "no_issue_seen":
        headline = (_text(locale, "照片未見明顯錯接，仍需親自確認。", "No obvious mismatch is visible; confirm the wiring yourself.")
                    if not counts["suspected"] and not counts["uncertain"] else _text(locale,
                    f"{pin} 照片未見明顯錯接，請親自確認。", f"No obvious mismatch is visible for {pin}; check it yourself."))
        role = None
    elif diagnosis.get("kind") == "row_position_check":
        subject = _wire_subject(pin, row.get("wire_colors", {}).get("component", {}), locale)
        headline = _text(locale, f"先核對{subject}的位置。", f"Check the position of {subject} first.")
        role = None
    elif row.get("comparison") == "different":
        headline = _text(locale, f"{pin} 這條線疑似接錯，請先核對。",
                         f"The {pin} wire may be miswired. Check it first.")
        role = None
    else:
        needed = {role: sum(role in result.get("diagnosis", {}).get("retake_roles", [])
                            and not (review.get("capture_plan") == ROW_CAPTURE_PLAN
                                     and set(result.get("diagnosis", {}).get("retake_roles", [])) == {"pi_side_a", "pi_side_b"})
                            for result in pending) for role in ROLES}
        shared_role = max(ROLES, key=lambda role: needed[role])
        if needed[shared_role] > 1:
            role = shared_role
            headline = _text(locale,
                "零件接頭的腳位尚未確認。" if role == "component_header" else "Pi 插接位置尚未確認。",
                "The module pin positions are not identified yet." if role == "component_header" else "The Pi connection positions are not identified yet.")
            next_step = (_text(locale, "補拍零件接頭，讓腳位標字與插頭底部入鏡。",
                              "Retake the module header with its labels and housing bases visible.")
                         if role == "component_header" else _pi_retake_text(review, role, locale))
        else:
            headline = _text(locale, f"{pin} 這條線還需要確認。", f"The {pin} wire still needs checking.")
        if (all(result.get("diagnosis", {}).get("module_identity_known") for result in pending)
                and any(result.get("diagnosis", {}).get("module_attachment_uncertain") for result in pending)):
            if role in {"pi_side_a", "pi_side_b"} or both_rows:
                headline = _text(locale, "零件標字與接頭位置已辨識，接著核對 Pi。",
                                 "Module labels and housing positions are identified; check the Pi next.")
            elif not role and any(not result.get("diagnosis", {}).get("module_attachment_confirmed") for result in pending):
                headline = _text(locale, "零件標字與接頭位置已辨識，兩端是否同一條線仍待核對。",
                                 "Module labels and housing positions are identified; check whether the endpoints belong to the same wire.")
        photo_note = _header_note(review, role)
        if photo_note:
            # Seeing exposed tips or a detached housing is useful information
            # even without a pin name. Do not erase it with "cannot see".
            label = _text(locale, "零件端" if role == "component_header" else "Pi 端",
                          "Module" if role == "component_header" else "Pi")
            if photo_note["state"] == "uncovered_pins":
                headline = _text(locale, f"{label}可見裸露排針。", f"Uncovered pin tips are visible at the {label} header.")
            elif photo_note["state"] == "detached":
                headline = _text(locale, f"{label}可見未套接的接頭。", f"An unattached connector is visible at the {label} header.")
            elif photo_note["state"] == "legacy_observation":
                # Preserve the observation as a quotation, not a new verdict
                # inferred from its words or the expected wiring.
                headline = _text(locale, "照片觀察：", "Photo observation: ") + photo_note["evidence"][:100]
            if photo_note["state"] in {"uncovered_pins", "detached", "legacy_observation"}:
                role = None
                next_step = _text(locale, "先對照接線圖核對插接狀態；要調整接線請先斷電。",
                                  "Check the connector placement against the diagram; power off before changing wiring.")
    if (review.get("no_progress_count", 0) >= 2 and diagnosis.get("status") == "uncertain"
            and row.get("comparison") != "different"
            and diagnosis.get("kind") != "row_position_check"
            and not (photo_note and photo_note["state"] in {"uncovered_pins", "detached", "legacy_observation"})):
        role = None
        next_step = _diagram_check_step(row, locale) + _text(locale, "仍無法判斷可記為「無法確定」。",
                           " Leave it uncertain if you cannot verify the connection.")
    if (not role and not both_rows and not photo_note and all(
            result.get("diagnosis", {}).get("status") == "uncertain"
            and result.get("diagnosis", {}).get("kind") != "row_position_check"
            and not result.get("diagnosis", {}).get("retake_roles")
            and result.get("comparison") != "different" for result in pending)):
        # Catalog order must not make the first wire look like the detected
        # problem when the photographs established no particular discrepancy.
        headline = _text(locale, "照片尚未找出明確的接線疑點。", "The photos have not identified a specific wiring concern.")
        next_step = _text(locale, "可展開逐線核對，沿同一條線確認兩端。",
                          "Expand the wire details and trace each wire to check both ends.")
    return dict(schema_version=2, headline=headline, next_step=next_step, retake_role=role, counts=counts,
                retake_target_row=capture_target_row(review, role),
                observation=photo_note["evidence"] if photo_note else "",
                observation_role=photo_note["role"] if photo_note else None,
                observation_source=photo_note["source"] if photo_note else None,
                results=deepcopy(sorted(review["results"], key=_review_priority)),
                evidence=diagnosis.get("evidence") or row.get("evidence", ""))


class GuidedWiringReview:
    def __init__(self, sessions):
        self.sessions = sessions

    def enable_dialogue(self, sid, conversation_id, epoch, guide_round):
        """Persist conversational guidance, without submitting any physical work."""
        service = self.sessions
        with service.lock:
            session = service.sessions[sid]
            flow = session.get("wiring_dialogue")
            if not flow or flow.get("conversation_id") != conversation_id or flow.get("epoch") != epoch:
                session["wiring_dialogue"] = dict(id=uuid4().hex, conversation_id=conversation_id,
                    epoch=epoch, guide_round=guide_round, events=[], current_event_id=None,
                    receipts={}, flight=None, last_photo_ids=[])
            self.sync_dialogue(session)
            service._save()

    def _dialogue_message(self, session, speaker, text, kind, **values):
        review, flow = session["wiring_review"], session["wiring_dialogue"]
        event_id = uuid4().hex
        metadata = dict(flow_id=flow["id"], event_id=event_id, review_id=review["id"],
            revision=review["revision"], round=review["round"], component_id=review["component_id"],
            capture_plan=review.get("capture_plan"),
            kind=kind, current=False, can_act=False, actions=[], **values)
        message = dict(id=event_id, role=speaker, text=text, created_at=time.time(), wiring_flow=metadata,
                       round=flow["guide_round"], epoch=flow["epoch"])
        if values.get("capture_id"):
            message["capture_ids"] = [values["capture_id"]]
        flow["events"].append(deepcopy(message))
        self.sessions._add_message(session, message)
        if speaker == "assistant":
            flow["current_event_id"] = event_id
        return message

    def sync_dialogue(self, session):
        """Materialise a step once per committed review state, never per render/read."""
        flow, review = session.get("wiring_dialogue"), session.get("wiring_review")
        if not flow or not review or flow.get("flight"):
            return
        # Freeze the completed duration on its original analysis event. Later
        # photos and analyses must not restart a historical message's clock.
        if review.get("analysis_elapsed_ms") is not None:
            for event in flow["events"]:
                metadata = event.get("wiring_flow", {})
                if (metadata.get("kind") == "analysing" and metadata.get("review_id") == review["id"]
                        and metadata.get("round") == review["round"]
                        and metadata.get("started_at") == review.get("analysis_started_at")):
                    metadata["elapsed_ms"] = review["analysis_elapsed_ms"]
        locale = (session.get("context") or {}).get("locale", "zh-TW")
        kind, values = "photo_request", {}
        if review["status"] == "stale" or session.get("context") is None:
            reasons = {
                "camera_changed": ("鏡頭來源已變更", "the camera source changed"),
                "context_changed": ("作品、程式或接線版本已變更", "the project, code or wiring changed"),
                "photos_expired": ("照片已過期", "the photographs expired"),
                "session_stopped": ("這輪核對已停止", "this review was stopped"),
            }
            reason = _text(locale, *reasons.get(review.get("error"), ("照片已失效", "the photographs are no longer valid")))
            kind, text = "error", _text(locale,
                f"{reason}，沒有完成分析。",
                f"Photo review stopped: {reason}. Analysis did not complete.")
            values["error"] = review.get("error")
        elif review["status"] == "analysing":
            kind, text = "analysing", _text(locale, "正在看照片…", "Looking at the photos…")
        elif review["status"] == "error":
            kind, text = "error", _text(locale, "分析未完成，照片已保留。", "Analysis did not finish. Your photos are retained.")
            values["error"] = review.get("error")
        elif review["status"] in {"ready", "needs_human"}:
            pending = [row for row in review["results"] if not review["reviews"].get(row["wire_id"])
                       or review["reviews"][row["wire_id"]].get("evidence_stale")]
            pending.sort(key=_review_priority)
            if pending:
                row = pending[0]
                summary = _review_summary(review, pending, locale)
                values = dict(wire_id=row["wire_id"], result=deepcopy(row), summary=summary)
                kind = "wire_review"
                text = summary["headline"]
            else:
                kind = "complete"
                confirmed = sum(v.get("decision") == "confirmed" and not v.get("evidence_stale") for v in review["reviews"].values())
                total = len(review["results"])
                text = _text(locale, f"已記錄：{confirmed}／{total} 條由你確認。功能測試需另外執行。", f"Recorded: {confirmed}/{total} wires confirmed by you. Functional testing is separate.")
        else:
            missing = next((role for role in ROLES if not photo_accepted(review, role)), None)
            if missing:
                values = dict(role=missing, photo_index=ROLES.index(missing) + 1, photo_total=len(ROLES))
                texts = {
                    "pi_side_a": ("拍 Pi 第一側，保留排針、插頭底部與板角。", "Photograph the first Pi side, including the header, housing bases and board corner."),
                    "pi_side_b": ("換另一側拍 Pi，露出被遮住的插頭底部。", "Photograph the opposite Pi side to reveal hidden housing bases."),
                    "component_header": ("拍零件接頭，讓腳位標字與插頭底部入鏡。", "Photograph the module header with its pin labels and housing bases visible."),
                }
                if review.get("capture_plan") == ROW_CAPTURE_PLAN:
                    texts.update({
                        "pi_side_a": ("先拍 Pi 內排（靠板中央），從板中央這側看向排針，拍到插頭底部與板角，避開兩排重疊。",
                                      "Photograph the Pi inner row, nearer the board centre. Look from the board-centre side; show housing bases and a board corner without overlapping rows."),
                        "pi_side_b": ("再拍 Pi 外排（靠板邊緣），從板外側看向排針，拍到插頭底部與板角，避開兩排重疊。",
                                      "Photograph the Pi outer row, nearer the board edge. Look from outside the board; show housing bases and a board corner without overlapping rows."),
                    })
                values["target_row"] = capture_target_row(review, missing)
                text = _text(locale, *texts[missing])
            else:
                kind, text = "analysis_request", _text(locale, "照片齊了，可以開始分析。", "The photos are ready to analyse.")
        if kind in {"analysing", "wire_review", "complete", "error"} and review.get("analysis_started_at") is not None:
            values.update(started_at=review["analysis_started_at"], elapsed_ms=review.get("analysis_elapsed_ms"))
        key = digest([review["id"], review["round"], review["revision"], kind, values.get("role"), values.get("wire_id")])
        if flow.get("step_key") == key:
            return
        flow["step_key"] = key
        self._dialogue_message(session, "assistant", text, kind, **values)

    def dialogue_projection(self, session, message):
        metadata = deepcopy(message["wiring_flow"])
        flow, review = session.get("wiring_dialogue", {}), session.get("wiring_review", {})
        # Imported messages are append-only. Timing is projected from the exact
        # persisted event so completed clocks survive subsequent photo rounds.
        event = next((event for event in flow.get("events", []) if event["id"] == metadata.get("event_id")), None)
        if event:
            source = event.get("wiring_flow", {})
            for key in ("started_at", "elapsed_ms"):
                if key in source:
                    metadata[key] = source[key]
        current = bool(message.get("role") == "assistant" and metadata.get("flow_id") == flow.get("id")
            and metadata.get("event_id") == flow.get("current_event_id")
            and metadata.get("review_id") == review.get("id") and metadata.get("round") == review.get("round")
            and metadata.get("revision") == review.get("revision"))
        # Upgrade only the current, exact result's presentation in the response.
        # Original receipts/history are untouched, and an old round can never
        # borrow the current cache or acquire a different wire's review action.
        if (current and metadata.get("kind") == "wire_review" and review.get("status") in {"ready", "needs_human"}
                and (metadata.get("summary") or {}).get("schema_version") != 2):
            pending = sorted((row for row in review.get("results", [])
                              if not review.get("reviews", {}).get(row["wire_id"])
                              or review["reviews"][row["wire_id"]].get("evidence_stale")), key=_review_priority)
            if pending and pending[0]["wire_id"] == metadata.get("wire_id"):
                metadata["summary"] = _review_summary(review, pending, (session.get("context") or {}).get("locale", "zh-TW"))
        busy = bool(flow.get("flight") or review.get("pending") or session.get("chat_pending")
            or session.get("capture_pending") or session.get("phase") in {"observing_photo", "observing_tft", "repair_analysing", "replying", "wiring_review_analysing"})
        available = bool(current and session.get("context") and session.get("status") not in {"paused", "stopped", "complete", "error"}
                         and review.get("status") != "stale" and not busy)
        kind = metadata.get("kind")
        actions = {"photo_request": ["capture"], "analysis_request": ["analyse", "capture", "crop"],
            "wire_review": ["review", "capture", "crop", "changed"], "complete": ["changed"],
            "error": ["analyse", "capture", "crop"]}.get(kind, []) if available else []
        if review.get("no_progress_count", 0) >= 2:
            actions = [op for op in actions if op not in {"capture", "crop", "analyse"}]
        metadata.update(current=current, can_act=bool(actions), actions=actions)
        return metadata

    def dialogue_guard(self, session, metadata, action):
        projection = self.dialogue_projection(session, dict(role="assistant", wiring_flow=metadata))
        if not projection["current"] or not projection["can_act"] or action.op not in projection["actions"]:
            raise ValueError("stale_wiring_dialogue")
        self._check(session, action)
        if action.op in {"capture", "crop"}:
            if action.role not in ROLES or (projection["kind"] == "photo_request" and action.role != projection.get("role")):
                raise ValueError("wiring_dialogue_role_mismatch")
        if action.op == "review" and action.wire_id != projection.get("wire_id"):
            raise ValueError("wiring_dialogue_wire_mismatch")

    def accept_dialogue_photo(self, sid, role):
        """Explicitly submitted pixels are selected, never a wiring confirmation."""
        service = self.sessions
        with service.lock:
            session = service.sessions[sid]
            review = session["wiring_review"]
            slot = review["slots"][role]
            action = WiringReviewAction(op="accept_photo", role=role, review_id=review["id"],
                revision=review["revision"], capture_id=slot["capture_id"], sha256=slot["sha256"])
            self.action(sid, action)
            flow = session["wiring_dialogue"]
            if slot["capture_id"] not in flow["last_photo_ids"]:
                flow["last_photo_ids"].append(slot["capture_id"])
                label = _photo_label(review, role, (session.get("context") or {}).get("locale", "zh-TW"))
                self._dialogue_message(session, "user", label, "photo", role=role,
                    capture_id=slot["capture_id"], image_url=slot["image_url"], target_row=slot.get("target_row"))

    def dialogue_action(self, sid, metadata, action, request_id, *, context=None, work=None):
        """CAS and receipt cover capture + selection as one human chat submission."""
        service = self.sessions
        action = action if isinstance(action, WiringReviewAction) else WiringReviewAction.model_validate(action)
        signature = digest([metadata, action.model_dump(), context])
        with service.lock:
            session = service.sessions[sid]
            flow = session.get("wiring_dialogue") or {}
            receipt = flow.get("receipts", {}).get(request_id)
            if receipt:
                if receipt["signature"] != signature:
                    raise ValueError("request_id_conflict")
                if receipt["state"] == "done":
                    return
                raise ValueError("action_result_unknown")
            self.dialogue_guard(session, metadata, action)
            flow["flight"] = request_id
            flow["receipts"][request_id] = dict(signature=signature, state="pending",
                before_binding=deepcopy(session["binding"]))
            service._save()
        try:
            if work:
                work()
            else:
                service.action(sid, "wiring_review", request_id, context=context,
                    wiring_review=action.model_dump())
            if action.op == "capture":
                self.accept_dialogue_photo(sid, action.role)
            with service.lock:
                session = service.sessions[sid]
                if action.op == "review":
                    locale = (session.get("context") or {}).get("locale", "zh-TW")
                    labels = {"confirmed": ("我已親自確認接對", "I personally confirmed this wire"),
                              "needs_change": ("我發現接錯，準備修正", "I found an incorrect connection and will correct it"),
                              "unsure": ("仍無法確定", "I am still unsure")}
                    self._dialogue_message(session, "user", _text(locale, *labels[action.decision]),
                        "human_decision", wire_id=action.wire_id, decision=action.decision)
                if action.op == "changed":
                    session["wiring_dialogue"]["guide_round"] = (session.get("context") or {}).get("guide_run", 0)
                    self._dialogue_message(session, "user", _text((session.get("context") or {}).get("locale", "zh-TW"),
                        "我已改動接線，重新拍攝這一輪照片。", "I changed the wiring and will take new photographs."), "human_decision")
                if action.op in {"review", "changed"}:
                    current_context = session["context"]
                    current_review = session["wiring_review"]
                    flow["receipts"][request_id]["guide_receipt"] = dict(request_id=request_id,
                        flow_id=flow["id"], context_epoch=flow["epoch"],
                        project_id=current_context["project"]["id"], project_revision=current_context["project"]["revision"],
                        op=action.op, wire_id=action.wire_id, decision=action.decision,
                        before_binding=deepcopy(flow["receipts"][request_id]["before_binding"]),
                        after_binding=deepcopy(session["binding"]),
                        guide_confirmations=deepcopy(current_context.get("guide_confirmations", {})),
                        guide_run=current_context.get("guide_run", 0), test_keys=deepcopy(current_context.get("test_keys", {})),
                        review_id=current_review["id"], round=current_review["round"],
                        context_fingerprint=digest(current_context))
                flow["receipts"][request_id]["state"] = "done"
        except Exception:
            with service.lock:
                flow["receipts"].pop(request_id, None)
            raise
        finally:
            with service.lock:
                flow["flight"] = None
                self.sync_dialogue(service.sessions[sid])
                service._save()

    def _check(self, session, body):
        if session.get("context") is None or session.get("status") in {"stopped", "complete"}:
            raise ValueError("session_not_active")
        review = session.get("wiring_review")
        if review and (body.review_id != review["id"] or body.revision != review["revision"]):
            raise ValueError("stale_wiring_review")
        if not review and body.op != "start":
            raise ValueError("wiring_review_required")
        return review

    def refresh_human_context(self, session, body, context, new_binding, *, apply=False):
        """Validate explicit human guide updates without treating them as AI facts.

        Withdrawing a checkbox is not a physical rewiring event. Only `changed`
        starts a new photo round. The action and context update commit together.
        """
        from app.debug_support import validate_project
        review = self._check(session, body)
        if not context or not new_binding:
            raise ValueError("context_required")
        validate_project(context.get("project"))
        if any(new_binding[k] != session["binding"].get(k) for k in new_binding if k not in {"guide_hash", "test_keys"}):
            raise ValueError("stale_debug_context")
        old = session["context"]
        if context.get("wiring_target") != old.get("wiring_target"):
            raise ValueError("stale_debug_context")
        before, after = old.get("guide_confirmations", {}), context.get("guide_confirmations", {})
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        wires = wiring_for(context["project"]["component_ids"])
        component_wires = {w["id"] for w in wires if w["componentId"] == review["component_id"]}
        if body.op == "review":
            if body.wire_id not in component_wires or changed - {body.wire_id}:
                raise ValueError("invalid_human_confirmation_change")
            if context.get("guide_run", 0) != old.get("guide_run", 0):
                raise ValueError("invalid_human_confirmation_change")
            if body.decision == "confirmed":
                wire = next(w for w in wires if w["id"] == body.wire_id)
                record = after.get(body.wire_id)
                signature = "|".join(str(wire[k]) for k in ("componentId", "componentPin", "boardPin", "connectionKind"))
                if not record or record.get("signature") != signature:
                    raise ValueError("invalid_human_confirmation_change")
                try:
                    datetime.fromisoformat(record["at"].replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError, AttributeError) as error:
                    raise ValueError("invalid_human_confirmation_change") from error
            elif body.wire_id in after:
                raise ValueError("human_confirmation_must_be_removed")
        else:
            scope = body.scope or ("component" if body.component_id else "all")
            if body.component_id is not None and body.component_id != review["component_id"]:
                raise ValueError("invalid_human_confirmation_change")
            # A declared physical change may clear the affected component or all
            # confirmations, but cannot add or silently edit another record.
            if any(k not in before or v != before[k] for k, v in after.items()):
                raise ValueError("invalid_human_confirmation_change")
            if any(k in after for k in component_wires):
                raise ValueError("changed_wiring_requires_unconfirmed_component")
            if scope == "all" and after:
                raise ValueError("changed_wiring_requires_unconfirmed_component")
            if scope == "component" and any(k not in component_wires for k in changed):
                raise ValueError("invalid_human_confirmation_change")
            if context.get("guide_run", 0) not in {old.get("guide_run", 0), old.get("guide_run", 0) + 1}:
                raise ValueError("invalid_human_confirmation_change")
        removed = set(before) - set(after)
        if (removed or body.op == "changed") and not self.sessions._wiring_edit_ready(session):
            raise ValueError("pi_busy_for_wiring")
        # Match componentTestKey, including null timestamps for unconfirmed wires.
        # Those keys name an incomplete configuration; they never grant readiness.
        for cid in context["project"]["component_ids"]:
            p = context["project"]
            rows = [["|".join(str(w[k]) for k in ("componentId", "componentPin", "boardPin", "connectionKind")),
                     after.get(w["id"], {}).get("at")] for w in p["wiring"] if w["componentId"] == cid]
            expected_key = json.dumps([p["id"], p["revision"], context.get("guide_run", 0), p["catalog_version"],
                p["profile_versions"].get(cid), rows], ensure_ascii=False, separators=(",", ":"))
            if context.get("test_keys", {}).get(cid) != expected_key:
                raise ValueError("invalid_human_test_key")
        if apply:
            session.update(context=deepcopy(context), binding=deepcopy(new_binding))
            self.sessions._adopt_tests(session)

    @staticmethod
    def _inputs_changed(session, review):
        review.update(revision=review["revision"] + 1, status="collecting", pending=False,
                      observations=[], terminal_observations=[], results=[], error=None, analysis_revision=None,
                      analysis_started_at=None, analysis_elapsed_ms=None)
        for record in review["reviews"].values():
            record["evidence_stale"] = True
        review["missing_roles"] = [r for r in ROLES if not review["slots"][r] or not review["slots"][r]["available"]]
        session.update(step_rev=session["step_rev"] + 1, status="awaiting_capture", phase="wiring_review",
                       capture_pending=False, chat_pending=False, capture_task=None)

    def action(self, sid, body, *, context=None):
        service = self.sessions
        body = body if isinstance(body, WiringReviewAction) else WiringReviewAction.model_validate(body)
        with service.lock:
            session = service.sessions[sid]
            review = self._check(session, body)
            if (body.op in {"capture", "accept_photo", "crop", "analyse"}
                    and (session.get("chat_pending") or session.get("capture_pending")
                         or session.get("phase") in {"observing_photo", "observing_tft", "repair_analysing", "replying"})):
                raise ValueError("model_call_in_progress")
            if review and review["no_progress_count"] >= 2 and body.op in {"capture", "crop"}:
                raise ValueError("human_review_required")
            human_binding = None
            if body.op in {"review", "changed"}:
                from app.debug_sessions import _binding
                human_binding = _binding(context, service.state.component_tests.target) if context else None
                self.refresh_human_context(session, body, context, human_binding)
            if body.op == "start":
                if body.component_id not in session["context"]["project"]["component_ids"]:
                    raise ValueError("unsupported_component")
                if any(j["state"] not in {"finished", "failed", "cancelled"} for j in service._public(session)["jobs"]):
                    raise ValueError("existing_work_requires_reconciliation")
                if review and review["component_id"] == body.component_id and review["status"] != "stale":
                    return
                cache = session.setdefault("wiring_review_components", {})
                if review and review["status"] != "stale":
                    cache[review["component_id"]] = deepcopy(review)
                    cache[review["component_id"]]["pending"] = False
                    if cache[review["component_id"]]["status"] == "analysing":
                        cache[review["component_id"]]["status"] = "collecting"
                    previous = review
                    review = deepcopy(cache.get(body.component_id)) or _new_review(body.component_id,
                        round_number=previous["round"], review_id=previous["id"])
                    review.update(id=previous["id"], round=previous["round"], revision=previous["revision"]+1)
                    # Shared Pi photos keep their original capture contract.
                    # Merely switching modules cannot relabel legacy side shots.
                    if "capture_plan" in previous:
                        review["capture_plan"] = previous["capture_plan"]
                    else:
                        review.pop("capture_plan", None)
                    if any(review["slots"][r] != previous["slots"][r] for r in ("pi_side_a", "pi_side_b")):
                        _archive_review(session, review, "shared_photo_updated")
                    moved = False
                    for role in ("pi_side_a", "pi_side_b"):
                        moved |= review["slots"][role] != previous["slots"][role]
                        review["slots"][role] = deepcopy(previous["slots"][role])
                    cached_views = {v["role"]: v for v in (review.get("last_opinion") or {}).get("views", [])}
                    for v in (previous.get("last_opinion") or {}).get("views", []):
                        if v["role"] != "component_header":
                            cached_views[v["role"]] = deepcopy(v)
                            review.setdefault("role_input_keys", {})[v["role"]] = previous.get("role_input_keys", {}).get(v["role"])
                    for role in ("pi_side_a", "pi_side_b"):
                        if role in previous.get("exit_inventory", {}):
                            review.setdefault("exit_inventory", {})[role] = deepcopy(previous["exit_inventory"][role])
                            review.setdefault("exit_input_keys", {})[role] = previous.get("exit_input_keys", {}).get(role)
                        evidence = review.setdefault("exit_evidence", {})
                        for key in list(evidence):
                            if key.startswith(role+":"):
                                del evidence[key]
                        evidence.update({k: deepcopy(v) for k, v in previous.get("exit_evidence", {}).items() if k.startswith(role+":")})
                    if cached_views:
                        review["last_opinion"] = dict(views=list(cached_views.values()))
                    if moved:
                        self._inputs_changed(session, review)
                    review["missing_roles"] = [r for r in ROLES if not review["slots"][r] or not review["slots"][r]["available"]]
                else:
                    cache.clear()
                    review = _new_review(body.component_id, round_number=review["round"]+1 if review else 1)
                session["wiring_review"] = review
                session.update(step_rev=session["step_rev"] + 1, status="awaiting_capture", phase="wiring_review",
                    capture_pending=False, chat_pending=False, capture_task=None,
                    instruction=("請分別拍攝 Pi 內排（靠板中央）、外排（靠板邊緣）與零件接頭；保持這輪接線不變，最後由你核對。"
                                 if review.get("capture_plan") == ROW_CAPTURE_PLAN else
                                 "請拍攝 Pi 排針兩側與零件接頭；保持這輪接線不變，最後由你核對。"))
            elif body.op == "changed":
                cache = session.setdefault("wiring_review_components", {})
                cache.pop(review["component_id"], None)
                saved_reviews = [review, *cache.values()]
                for saved in saved_reviews:
                    _archive_review(session, saved, "user_changed_wiring")
                # Physical edits start a wholly new photograph round, including
                # unaffected component images. Unaffected human guide records
                # can remain, but no old photo inventory enters the new round.
                cache.clear()
                for entry in session["evidence"]:
                    entry.update(current=False, invalidated_reason="user_changed_wiring")
                session["wiring_review"] = _new_review(review["component_id"], round_number=review["round"] + 1,
                    review_id=review["id"], revision=review["revision"] + 1)
                session.update(step_rev=session["step_rev"] + 1, status="awaiting_capture", phase="wiring_review",
                    capture_pending=False, chat_pending=False, capture_task=None,
                    instruction="已開始新的接線照片輪次；請拍摄目前接線。")
            elif review["status"] == "stale":
                raise ValueError("stale_wiring_review")
            elif body.op == "accept_photo":
                if review["pending"] or review["status"] == "analysing":
                    raise ValueError("model_call_in_progress")
                slot = review["slots"][body.role]
                if not slot or not slot.get("available"):
                    raise ValueError("wiring_review_photo_required")
                if body.capture_id != slot["capture_id"] or body.sha256 != slot["sha256"]:
                    raise ValueError("stale_wiring_review_photo")
                if not any(e["id"] == slot["capture_id"] and e.get("current") and e.get("available")
                           for e in session["evidence"]):
                    raise ValueError("wiring_review_photos_expired")
                if photo_accepted(review, body.role):
                    return
                slot["photo_acceptance"] = dict(capture_id=slot["capture_id"], sha256=slot["sha256"],
                    round=review["round"], accepted_at=datetime.now(timezone.utc).isoformat(), source="human")
                review["revision"] += 1
            elif body.op == "crop":
                slot = review["slots"][body.role]
                if not slot or not slot["available"]:
                    raise ValueError("wiring_review_photo_required")
                if body.crop is not None:
                    _crop_pixels(body.crop, slot["size"])
                if slot["crop"] == (list(body.crop) if body.crop else None):
                    return
                _archive_review(session, review, "crop_updated")
                slot.update(crop=list(body.crop) if body.crop else None, crop_source="manual" if body.crop else "none")
                self._inputs_changed(session, review)
            elif body.op == "review":
                if review["status"] not in {"ready", "needs_human"} or not any(r["wire_id"] == body.wire_id for r in review["results"]):
                    raise ValueError("wiring_review_result_required")
                review["reviews"][body.wire_id] = dict(decision=body.decision, source="human", note=body.note,
                    at=datetime.now(timezone.utc).isoformat(), review_revision=review["analysis_revision"], evidence_stale=False,
                    wire_id=body.wire_id, review_id=review["id"], round=review["round"],
                    capture_ids=[slot["capture_id"] for slot in review["slots"].values() if slot])
                review["revision"] += 1
            elif body.op == "analyse":
                if review["pending"] or review["status"] == "analysing":
                    raise ValueError("model_call_in_progress")
                if review["missing_roles"]:
                    raise ValueError("wiring_review_photos_incomplete")
                if review.get("photo_flow_version", 1) >= 2 and not all(photo_accepted(review, role) for role in ROLES):
                    raise ValueError("wiring_review_photos_not_accepted")
                if review["no_progress_count"] >= 2:
                    raise ValueError("human_review_required")
                key = analysis_input_key(review, session)
                if review["results"] and review.get("last_input_key") == key:
                    return
                if review.get("last_opinion") and review.get("last_input_key") == key:
                    opinion = ReviewOpinion.model_validate(review["last_opinion"])
                    pins = _board_pins()
                    wires = [w for w in wiring_for(session["context"]["project"]["component_ids"]) if w["componentId"] == review["component_id"]]
                    module = json.loads((ROOT / "profiles/components" / review["component_id"] / "vision_profile.json").read_text(encoding="utf-8"))
                    component_pins = {p["id"] for p in module["pins"]}
                    candidates = _canonical_candidates(opinion, review, pins, component_pins)
                    terminals = _canonical_module_terminals(opinion, review, component_pins)
                    review.update(status="ready", observations=candidates, terminal_observations=terminals,
                        results=compare_candidates(candidates, wires, pins, session["context"].get("locale", "zh-TW"), opinion.wire_paths,
                                                   capture_plan=review.get("capture_plan"), terminal_observations=terminals),
                        analysis_revision=review["revision"], revision=review["revision"]+1, error=None)
                    self.sync_dialogue(session)
                    service._save()
                    return
                if session["budget"]["model_calls"] + model_calls_needed(review, session) > session["budget"]["max_model_calls"]:
                    raise ValueError("model_call_limit_reached")
                review.update(status="analysing", pending=True, revision=review["revision"] + 1, error=None,
                              input_key=key, analysis_started_at=time.time(), analysis_elapsed_ms=None)
                session.update(step_rev=session["step_rev"] + 1, status="awaiting_capture", phase="wiring_review_analysing",
                               capture_pending=False, chat_pending=False, capture_task=None,
                               instruction="先辨識出線口與線色，再獨立核對腳位及走線；結果需要你人工確認。")
            if body.op != "capture":
                if human_binding is not None:
                    # Validation above happens against the original review ID;
                    # commit only after the requested operation is accepted.
                    session.update(context=deepcopy(context), binding=deepcopy(human_binding))
                    service._adopt_tests(session)
                self.sync_dialogue(session)
                service._save()
                return
            expected_id, expected_revision, expected_step = review["id"], review["revision"], session["step_rev"]
            target = "module_header" if body.role == "component_header" else "pi_header"
            context = deepcopy(session["context"])
        # Capture only one requested role. Other role originals are retained.
        if service.capture_fn is not None:
            frozen = service.capture_fn(service.state, target, earliest_ms=None)
        else:
            from app.debug_capture import capture_debug_evidence
            # A role is one newly selected raw frame. Paired endpoint locators
            # may refer to two different frames and cannot replace this source.
            frozen = capture_debug_evidence(service.state, target, wiring_target=None, response_mode="fast")
        images, metadata = deepcopy(frozen)
        frame = _decode(images["overview"])
        height, width = frame.shape[:2]
        if metadata.get("size") != [width, height]:
            raise ValueError("wiring_review_image_size_mismatch")
        metadata["sha256"] = hashlib.sha256(images["overview"]).hexdigest()
        with service.lock:
            session = service.sessions[sid]
            review = session["wiring_review"]
            if review["id"] != expected_id or review["revision"] != expected_revision or session["step_rev"] != expected_step:
                raise ValueError("stale_wiring_review")
            entry = service._capture(sid, target, frozen=(images, metadata), expected_step=expected_step)
            entry.update(wiring_review_id=review["id"], wiring_round=review["round"], role=body.role,
                         capture_plan=review.get("capture_plan"), target_row=capture_target_row(review, body.role),
                         component_id=review["component_id"] if body.role == "component_header" else "raspberry-pi-5")
            suggested = supported_crop(metadata, body.role, [width, height])
            _archive_review(session, review, "photo_replaced")
            review["slots"][body.role] = dict(role=body.role, capture_id=entry["id"], image_url=entry["url"],
                target_row=capture_target_row(review, body.role),
                size=[width, height], sha256=metadata["sha256"], crop=suggested, suggested_crop=suggested,
                crop_source="auto" if suggested else "none", available=True, wiring_round=review["round"],
                component_id=review["component_id"] if body.role == "component_header" else "raspberry-pi-5",
                source=metadata.get("source"), mirrored=metadata.get("mirrored") if isinstance(metadata.get("mirrored"), bool) else None,
                camera_id=metadata.get("camera_id"), captured_at=metadata.get("captured_at"), frame_id=metadata.get("frame_id"),
                quality=deepcopy(metadata.get("quality", {})))
            self._inputs_changed(session, review)
            self.sync_dialogue(session)
            service._save()

    def import_photo(self, sid, body, raw, *, provenance, still_current):
        """Import authorised immutable phone pixels without claiming webcam pose.

        The mobile service supplies provenance and a pairing/context guard.
        Capture identity is checked before decoding and again when committing.
        """
        service = self.sessions
        body = body if isinstance(body, WiringReviewAction) else WiringReviewAction.model_validate(body)
        if body.op != "capture" or not isinstance(raw, bytes) or not raw:
            raise ValueError("wiring_review_image_invalid")
        with service.lock:
            session = service.sessions[sid]
            review = self._check(session, body)
            if not still_current() or review["status"] == "stale":
                raise ValueError("stale_wiring_review")
            if (session.get("chat_pending") or session.get("capture_pending") or review.get("pending")
                    or session.get("phase") in {"observing_photo", "observing_tft", "repair_analysing", "replying", "wiring_review_analysing"}):
                raise ValueError("model_call_in_progress")
            if service._camera() != session["camera"]:
                raise ValueError("camera_changed")
            if review["no_progress_count"] >= 2:
                raise ValueError("human_review_required")
            expected_step, expected_binding = session["step_rev"], deepcopy(session["binding"])
            expected_camera = deepcopy(session["camera"])
        frame = _decode(raw)
        height, width = frame.shape[:2]
        sha = hashlib.sha256(raw).hexdigest()
        if provenance.get("size") != [width, height] or provenance.get("sha256") != sha:
            raise ValueError("wiring_review_image_size_mismatch")
        with service.lock:
            session = service.sessions[sid]
            review = self._check(session, body)
            if (not still_current() or session["step_rev"] != expected_step
                    or session["binding"] != expected_binding or session["camera"] != expected_camera
                    or service._camera() != expected_camera):
                raise ValueError("stale_wiring_review")
            if (session.get("chat_pending") or session.get("capture_pending") or review.get("pending")
                    or session.get("phase") in {"observing_photo", "observing_tft", "repair_analysing", "replying", "wiring_review_analysing"}):
                raise ValueError("model_call_in_progress")
            from app.debug_sessions import MAX_CAPTURES, MAX_CAPTURE_BYTES
            stored = service.images.setdefault(sid, {})
            if len(stored) >= MAX_CAPTURES or sum(map(len, stored.values())) + len(raw) > MAX_CAPTURE_BYTES:
                raise ValueError("capture_limit_reached")
            capture_id = uuid4().hex
            target = "module_header" if body.role == "component_header" else "pi_header"
            url = f"/api/debug/sessions/{sid}/evidence/{capture_id}"
            captured_at = datetime.now(timezone.utc).isoformat()
            entry = dict(id=capture_id, session_id=sid, url=url, target=target, available=True, current=True,
                source="phone_upload", captured_at=captured_at, size=[width, height], sha256=sha,
                project_id=session["binding"]["project_id"], wiring_hash=session["binding"]["wiring_hash"],
                code_hash=session["binding"]["code_hash"], guide_hash=session["binding"]["guide_hash"],
                target_id=session["binding"]["target_id"], wiring_review_id=review["id"],
                wiring_round=review["round"], role=body.role, provenance=deepcopy(provenance),
                capture_plan=review.get("capture_plan"), target_row=capture_target_row(review, body.role),
                component_id=review["component_id"] if body.role == "component_header" else "raspberry-pi-5",
                views=[dict(name="overview", mime_type="image/png" if raw.startswith(b"\x89PNG") else "image/jpeg", sha256=sha, url=url)])
            _archive_review(session, review, "photo_replaced")
            stored[capture_id] = raw
            session["evidence"].append(entry)
            session["budget"]["captures"] += 1
            review["slots"][body.role] = dict(role=body.role, capture_id=capture_id, image_url=url,
                target_row=capture_target_row(review, body.role),
                size=[width, height], sha256=sha, crop=None, suggested_crop=None, crop_source="none",
                available=True, wiring_round=review["round"], component_id=entry["component_id"],
                source="phone_upload", captured_at=captured_at, provenance=deepcopy(provenance))
            self._inputs_changed(session, review)
            self.sync_dialogue(session)
            service._save()

    def tick(self, sid):
        service = self.sessions
        with service.lock:
            session = service.sessions[sid]
            review = session.get("wiring_review")
            if not review or not review["pending"]:
                return
            review["pending"] = False
            snapshot, selection = deepcopy(review), deepcopy(session)
            expected_step = session["step_rev"]
            capture_ids = {s["capture_id"] for s in review["slots"].values()}
            entries = [deepcopy(e) for e in session["evidence"] if e["id"] in capture_ids]
            originals = {role: service.images.get(sid, {}).get(slot["capture_id"]) for role, slot in review["slots"].items()}
            service._save()
        started = time.monotonic()
        try:
            if len(entries) != 3 or any(not e.get("available") or not e.get("current") for e in entries):
                raise ValueError("wiring_review_photos_expired")
            board_pins = _board_pins()
            wires = [w for w in wiring_for(selection["context"]["project"]["component_ids"]) if w["componentId"] == snapshot["component_id"]]
            component_pins = {w["componentPin"] for w in wires}
            # Include bare optional terminals such as BLK in the inventory.
            module = json.loads((ROOT / "profiles/components" / snapshot["component_id"] / "vision_profile.json").read_text(encoding="utf-8"))
            component_pins.update(p["id"] for p in module["pins"])
            def generate(prompt, schema, paths, remaining):
                answer = service._ask(sid, prompt, schema, entries, trusted_paths=paths,
                    generate_options={"timeout_s": remaining}, expected_step=expected_step)
                with service.lock:
                    return answer, deepcopy(service.sessions[sid].get("last_model_receipt") or {})

            def remember_exits(exits, keys, evidence, stages):
                # Keep a successful inventory when the pin turn fails, but never
                # attach it to a newer round, replaced photo or changed session.
                with service.lock:
                    current = service.sessions[sid]
                    review = current.get("wiring_review")
                    if (current["step_rev"] != expected_step or not review
                            or review["id"] != snapshot["id"] or review["revision"] != snapshot["revision"]
                            or review["status"] != "analysing"):
                        raise ValueError("session_step_changed")
                    review.update(exit_inventory=deepcopy(exits), exit_input_keys=deepcopy(keys),
                                  exit_evidence=deepcopy(evidence), pipeline_stages=deepcopy(stages))
                    service._save()

            with tempfile.TemporaryDirectory(prefix="boardvision-wiring-review-") as directory:
                pipeline = inspect_wiring_photos(snapshot, selection, originals, board_pins, component_pins,
                    wires, directory, generate=generate, remember_exits=remember_exits)
            opinion = pipeline["opinion"]
            snapshot["exit_evidence"] = pipeline["exit_evidence"]
            candidates = _canonical_candidates(opinion, snapshot, board_pins, component_pins)
            terminals = _canonical_module_terminals(opinion, snapshot, component_pins)
            rows = compare_candidates(candidates, wires, board_pins, selection["context"].get("locale", "zh-TW"), opinion.wire_paths,
                                      capture_plan=snapshot.get("capture_plan"), terminal_observations=terminals)
            progress_key = digest([sorted((c["role"], c["pin_id"] or "", c.get("module_pin_id") or "", c["color"], c["color_visibility"], c["contact"]) for c in candidates),
                sorted((term.get("pin_id") or "", term["state"]) for term in terminals),
                [(r["wire_id"], r["diagnosis"]["status"], r["diagnosis"].get("kind"), r["diagnosis"]["observed_board_pin"], r["diagnosis"]["observed_component_pin"]) for r in rows]])
            unresolved = any(r["diagnosis"]["status"] == "uncertain" for r in rows)
            count = snapshot["no_progress_count"] + 1 if unresolved and progress_key == snapshot.get("last_progress_key") else 0
            with service.lock:
                current = service.sessions[sid]
                review = current.get("wiring_review")
                if (current["step_rev"] != expected_step or not review or review["id"] != snapshot["id"]
                        or review["revision"] != snapshot["revision"] or review["status"] != "analysing"):
                    return
                receipt = deepcopy(current.get("last_model_receipt") or {})
                analysis_statistics = {key: pipeline[key] for key in
                    ("analysis_mode", "cloud_call_count", "pipeline_elapsed_ms") if key in pipeline}
                receipt.update(image_inputs=pipeline["image_inputs"], pipeline_version=pipeline["pipeline_version"],
                               capture_plan=review.get("capture_plan"),
                               preparation_ms=pipeline["preparation_ms"],
                               stages=pipeline["stages"],
                               reused_roles=[r for r in ROLES if r not in pipeline["changed_roles"]],
                               review_id=review["id"], wiring_round=review["round"], **analysis_statistics)
                current["last_model_receipt"] = deepcopy(receipt)
                review.update(status="needs_human" if count >= 2 else "ready", observations=candidates,
                    terminal_observations=terminals, results=rows,
                    no_progress_count=count, last_progress_key=progress_key, last_input_key=snapshot["input_key"],
                    last_opinion=opinion.model_dump(), role_input_keys=pipeline["role_input_keys"],
                    exit_inventory=pipeline["exit_inventory"], exit_input_keys=pipeline["exit_input_keys"],
                    exit_evidence=pipeline["exit_evidence"], pipeline_version=pipeline["pipeline_version"],
                    pipeline_stages=pipeline["stages"],
                    analysis_revision=review["revision"], revision=review["revision"] + 1,
                    model_receipt=receipt, elapsed_ms=round((time.monotonic()-started)*1000),
                    analysis_elapsed_ms=self._analysis_elapsed(snapshot), error=None, **analysis_statistics)
                current.update(phase="wiring_review", instruction="請對照照片核對各條線；AI 的線色比較不會代替你的接線確認。")
                self.sync_dialogue(current)
                service._save()
        except Exception as error:
            with service.lock:
                current = service.sessions.get(sid, {})
                review = current.get("wiring_review")
                if (review and review["id"] == snapshot["id"] and review["revision"] == snapshot["revision"]
                        and current.get("step_rev") == expected_step):
                    review.update(status="error", error=str(error), pending=False, revision=review["revision"] + 1,
                                  elapsed_ms=round((time.monotonic()-started)*1000),
                                  analysis_elapsed_ms=self._analysis_elapsed(snapshot))
                    current.update(phase="wiring_review", instruction="這次照片分析未完成，原圖保留；可重新分析或人工核對。")
                    self.sync_dialogue(current)
                    service._save()

    @staticmethod
    def _analysis_elapsed(review):
        started_at = review.get("analysis_started_at")
        return max(0, round((time.time() - started_at) * 1000)) if started_at is not None else None
