"""Advisory row checks with synthetic source-bound observations; no cloud calls."""
from copy import deepcopy

from app.guided_wiring_review import _review_priority, _review_summary, compare_candidates
from app.wiring_photo_pipeline import ReviewWirePath


PINS = {"GPIO17": {"index": 11, "design_row": "inner"},
        "GPIO18": {"index": 12, "design_row": "outer"},
        "GPIO15": {"index": 10, "design_row": "outer"}}
WIRE = dict(id="module:signal", componentPin="SIGNAL", boardPin="GPIO17", connectionKind="direct")


def candidate(role, name, *, colour="yellow", pin=None, row="outer", module=False):
    source = dict(capture_id=f"capture-{role}", source_sha256={
        "pi_side_a": "a", "pi_side_b": "b", "component_header": "c"}[role] * 64,
        source_size=[1600, 1200])
    return dict(id=f"{role}:{name}", role=role, pin_id=pin, physical_pin=PINS.get(pin, {}).get("index"),
        module_pin_id="SIGNAL" if module else None,
        module_pin_evidence="SIGNAL label aligns with this housing." if module else "",
        pin_evidence="Visible board corner and housing base.", contact="uncertain" if module else "covers_pin",
        color=colour, color_visibility="clear", evidence="Visible insulation.", limitations="", **source,
        pin_seat=None if module else dict(image_id=role, row=row, column=5,
            base_box=[.2, .3, .25, .4], orientation_anchor="Board edge and USB end are visible.",
            count_evidence="Estimated column.", **source))


def observations():
    return [candidate("pi_side_a", "a", pin="GPIO15"),
            candidate("pi_side_b", "b", pin="GPIO15"),
            candidate("component_header", "m", module=True)]


def compare(items, *, wires=None, paths=()):
    return compare_candidates(items, wires or [WIRE], PINS, wire_paths=paths, capture_plan="pi_rows_v1")


def assert_no_row_clue(items, **kwargs):
    assert not any(row["diagnosis"].get("kind") == "row_position_check" for row in compare(items, **kwargs))


def test_two_source_row_clue_survives_column_drift_without_claiming_pin_or_same_wire():
    items = observations()
    items[1].update(pin_id=None, physical_pin=None, contact="uncertain", color_visibility="partial")
    items[1]["pin_seat"]["column"] = 6
    before = deepcopy(items)
    row = compare(items)[0]
    finding = row["diagnosis"]
    assert finding["kind"] == "row_position_check" and finding["status"] == "uncertain"
    assert finding["expected_row"] == "inner" and finding["candidate_row"] == "outer"
    assert finding["row_candidate_ids"] == ["pi_side_a:a", "pi_side_b:b"]
    assert finding["retake_roles"] == [] and row["same_wire"] == "uncertain"
    assert finding["observed_board_pin"] is None and finding["observed_physical_pin"] is None
    summary = _review_summary(dict(results=[row], no_progress_count=2), [row], "zh-TW")
    assert summary["headline"] == "先核對黃色 SIGNAL 線的位置。"
    assert "另一排" in summary["evidence"] and "沿線核對" in summary["evidence"]
    assert "接線圖" in summary["next_step"] and summary["retake_role"] is None
    assert all(text not in summary["headline"] + summary["next_step"] for text in ("接反", "Pin 10", "GPIO15", "補拍"))
    generic = deepcopy(row)
    generic["diagnosis"].pop("kind")
    assert sorted([generic, row], key=_review_priority)[0] is row
    assert items == before


def test_reciprocal_and_missing_terminal_findings_keep_priority_over_row_check():
    items = observations()
    for item in items[:2]:
        item.update(pin_id="GPIO18", physical_pin=12)
    for role in ("pi_side_a", "pi_side_b"):
        items.append(candidate(role, "other", colour="purple", pin="GPIO17", row="inner"))
    other = candidate("component_header", "other", colour="purple", module=True)
    other["module_pin_id"] = "MODE"
    items.append(other)
    wires = [WIRE, dict(id="module:mode", componentPin="MODE", boardPin="GPIO18", connectionKind="direct")]
    rows = compare(items, wires=wires)
    assert all(row["diagnosis"]["kind"] == "reciprocal_endpoint_swap" for row in rows)
    row_check = compare(observations())[0]
    missing = deepcopy(row_check)
    missing["diagnosis"].update(status="suspected", kind="unconnected_terminal")
    assert sorted([row_check, rows[0], missing], key=_review_priority) == [missing, rows[0], row_check]


def test_requested_photo_row_cannot_replace_missing_observed_seat():
    items = observations()
    items[1]["pin_seat"] = None
    items[1]["requested_row"] = "outer"
    assert_no_row_clue(items)


def test_stale_seat_or_same_source_repeated_as_two_views_cannot_supply_two_view_clue():
    items = observations()
    items[1]["pin_seat"]["source_sha256"] = "d" * 64
    assert_no_row_clue(items)
    items = observations()
    items[1]["source_sha256"] = items[1]["pin_seat"]["source_sha256"] = items[0]["source_sha256"]
    assert_no_row_clue(items)


def test_repeated_colour_on_either_endpoint_does_not_create_row_correspondence():
    items = observations()
    items.append(candidate("pi_side_a", "duplicate", pin="GPIO18"))
    assert_no_row_clue(items)
    items = observations()
    other = candidate("component_header", "duplicate", module=True)
    other["module_pin_id"] = "MODE"
    items.append(other)
    assert_no_row_clue(items)


def test_opposing_rows_and_matching_design_row_are_not_discrepancy_clues():
    items = observations()
    items[1]["pin_seat"]["row"] = "inner"
    assert_no_row_clue(items)
    items[0]["pin_seat"]["row"] = "inner"
    assert_no_row_clue(items)


def test_no_visible_base_or_conflicting_colour_at_same_position_blocks_row_clue():
    items = observations()
    for item in items[:2]:
        item["contact"] = "uncertain"
    assert_no_row_clue(items)
    items = observations()
    items.append(candidate("pi_side_a", "conflict", colour="green", pin="GPIO15"))
    assert_no_row_clue(items)


def test_traceable_route_keeps_its_own_result_and_is_not_replaced_by_row_hypothesis():
    items = observations()
    items[2].update(pin_id="SIGNAL", contact="covers_pin")
    path = ReviewWirePath(wire_id=WIRE["id"], board_connector_id=items[0]["id"],
        component_connector_id=items[2]["id"], visibility="traceable", evidence="A visible continuous route joins the housings.")
    row = compare(items, paths=[path])[0]
    assert row["diagnosis"].get("kind") != "row_position_check"
    assert row["diagnosis"]["status"] == "suspected" and row["same_wire"] == "consistent"
    assert row["diagnosis"]["observed_board_pin"] == "GPIO15"


def test_no_specific_clue_does_not_turn_first_catalog_wire_into_the_main_problem():
    items = observations()
    for item in items[:2]:
        item.update(pin_id="GPIO17", physical_pin=11)
        item["pin_seat"]["row"] = "inner"
    row = compare(items)[0]
    summary = _review_summary(dict(results=[row]), [row], "zh-TW")
    assert summary["headline"] == "照片尚未找出明確的接線疑點。"
    assert summary["next_step"] == "可展開逐線核對，沿同一條線確認兩端。"
    assert "SIGNAL" not in summary["headline"] + summary["next_step"]
    assert row["expected"]["component_pin"] == "SIGNAL" and row["diagnosis"]["status"] == "uncertain"
