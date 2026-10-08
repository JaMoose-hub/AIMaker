"""Synthetic endpoint hypotheses; no real-photo, route or electrical acceptance."""
from copy import deepcopy

from app.guided_wiring_review import _canonical_candidates, _review_summary, compare_candidates
from app.wiring_photo_pipeline import ReviewOpinion, ReviewWirePath, ROLES


PINS = {"GPIO17": {"index": 11, "design_row": "inner"},
        "GPIO18": {"index": 12, "design_row": "outer"},
        "GPIO22": {"index": 15, "design_row": "inner"}}
WIRES = [dict(id="sensor:a", boardPin="GPIO17", componentPin="SIGNAL_A", connectionKind="direct"),
         dict(id="sensor:b", boardPin="GPIO18", componentPin="SIGNAL_B", connectionKind="direct")]


def candidate(role, name, pin, colour, *, module=False):
    return dict(id=f"{role}:{name}", role=role, pin_id=None if module else pin,
                physical_pin=PINS.get(pin, {}).get("index"), module_pin_id=pin if module else None,
                module_pin_evidence="Printed label aligns with this housing." if module else "",
                pin_evidence="Visible anchor, row and counted housing position." if not module else "Base partly hidden.",
                contact="uncertain" if module else "covers_pin", color=colour, color_visibility="clear",
                evidence="Visible insulation at this housing.", position="Test position", limitations="", box=None)


def observations():
    return [candidate("pi_side_a", "a", "GPIO17", "purple"),
            candidate("pi_side_a", "b", "GPIO18", "yellow"),
            candidate("component_header", "a", "SIGNAL_A", "yellow", module=True),
            candidate("component_header", "b", "SIGNAL_B", "purple", module=True)]


def compare(items=None, *, wires=None, paths=()):
    return compare_candidates(observations() if items is None else items, WIRES if wires is None else wires,
                              PINS, wire_paths=paths, capture_plan="pi_rows_v1")


def assert_uncertain(rows):
    assert all(row["diagnosis"]["status"] == "uncertain" for row in rows)
    assert all(row["same_wire"] == "uncertain" for row in rows)
    assert not any(row["diagnosis"].get("kind") == "reciprocal_endpoint_swap" for row in rows)


def test_reciprocal_label_only_endpoints_produce_suspicion_and_short_summary_without_mutation():
    items = observations()
    before = deepcopy(items)
    rows = compare(items)
    assert [row["diagnosis"]["status"] for row in rows] == ["suspected", "suspected"]
    for row in rows:
        finding = row["diagnosis"]
        assert finding["kind"] == "reciprocal_endpoint_swap"
        assert finding["observed_board_pin"] is None and finding["observed_component_pin"] is None
        assert finding["module_attachment_uncertain"] and not finding["module_attachment_confirmed"]
        assert finding["retake_roles"] == [] and row["same_wire"] == "uncertain"
        assert row["authority"] == "visual_advisory" and "passed" not in row and "confirmed" not in row
    assert rows[0]["diagnosis"]["partner_component_pin"] == "SIGNAL_B"
    assert rows[0]["diagnosis"]["candidate_board_pin"] == "GPIO18"
    assert rows[0]["diagnosis"]["candidate_physical_pin"] == 12
    summary = _review_summary(dict(results=rows), rows, "zh-TW")
    assert summary["headline"] == "SIGNAL_A 與 SIGNAL_B 疑似接反。"
    assert "黃色 SIGNAL_A 線" in summary["next_step"]
    assert "紫色 SIGNAL_B 線" in summary["next_step"] and "接線圖" in summary["next_step"]
    assert "Pi Pin" not in summary["next_step"]
    assert summary["retake_role"] is None and items == before


def test_agreeing_views_of_identified_pin_are_not_duplicate_wires():
    items = observations()
    items.extend([candidate("pi_side_b", "x", "GPIO17", "purple"),
                  candidate("pi_side_b", "y", "GPIO18", "yellow")])
    assert all(row["diagnosis"]["status"] == "suspected" for row in compare(items))


def test_one_obscured_opposite_view_does_not_erase_clear_pi_observation():
    items = observations()
    other = candidate("pi_side_b", "x", None, "purple")
    other.update(contact="uncertain", pin_evidence="The other row hides this base.")
    items.append(other)
    rows = compare(items)
    assert all(row["diagnosis"]["status"] == "suspected" for row in rows)
    assert all(row["same_wire"] == "uncertain" for row in rows)


def test_colour_cannot_supply_missing_or_ungrounded_pi_identity():
    items = observations()
    items[0]["pin_id"] = None
    assert_uncertain(compare(items))
    items = observations()
    items[0]["pin_evidence"] = " "
    assert_uncertain(compare(items))


def test_ambiguous_module_labels_and_repeated_module_colour_block_pair():
    items = observations()
    items.append(candidate("component_header", "third", "OTHER", "yellow", module=True))
    assert_uncertain(compare(items))
    items = observations()
    items[2]["module_pin_id"] = None
    assert_uncertain(compare(items))


def test_same_colour_competing_pi_housings_in_one_view_block_pair():
    items = observations()
    items.append(candidate("pi_side_a", "extra", None, "yellow"))
    assert_uncertain(compare(items))


def test_cross_view_colour_or_identified_pin_conflict_blocks_pair():
    items = observations()
    items.append(candidate("pi_side_b", "conflict", "GPIO17", "red"))
    assert_uncertain(compare(items))
    items = observations()
    items.append(candidate("pi_side_b", "other-pin", "GPIO22", "yellow"))
    assert_uncertain(compare(items))


def test_only_unclear_colour_cannot_accuse_a_swap():
    items = observations()
    items[2]["color_visibility"] = "partial"
    assert_uncertain(compare(items))


def test_nonreciprocal_colours_and_intermediate_connections_do_not_form_pair():
    items = observations()
    items[0]["color"] = "red"
    assert_uncertain(compare(items))
    wires = deepcopy(WIRES)
    wires[0]["connectionKind"] = "divider"
    assert_uncertain(compare(wires=wires))


def test_independently_traced_route_retains_precedence_over_colour_hypothesis():
    items = observations()
    for item in items:
        if item["role"] == "component_header":
            item.update(pin_id=item["module_pin_id"], contact="covers_pin")
    path = ReviewWirePath(wire_id="sensor:a", board_connector_id="pi_side_a:a",
                         component_connector_id="component_header:a", visibility="traceable",
                         evidence="Distinctive marking and visible route connect these exact housings.")
    rows = compare(items, paths=[path])
    assert rows[0]["diagnosis"]["status"] == "no_issue_seen" and rows[0]["same_wire"] == "consistent"
    assert rows[1]["diagnosis"]["status"] == "uncertain"
    assert all("kind" not in row["diagnosis"] for row in rows)


def test_matching_colours_still_never_create_pass_or_same_wire_proof():
    items = observations()
    items[0]["color"], items[1]["color"] = "yellow", "purple"
    rows = compare(items)
    assert_uncertain(rows)
    assert all(row["comparison"] == "similar" for row in rows)
    assert all("passed" not in row and "confirmed" not in row for row in rows)


def test_source_bound_candidate_seat_survives_uncertain_contact_and_rejects_stale_source():
    items = observations()
    slots = {role: dict(capture_id=f"capture-{role}", sha256=f"sha-{role}", size=[4000, 3000]) for role in ROLES}
    views = []
    for role in ROLES:
        connectors = []
        for item in items:
            if item["role"] != role:
                continue
            row = dict(id=item["id"].split(":")[-1], position=item["position"],
                       contact=item["contact"], pin_id=item["pin_id"], pin_evidence=item["pin_evidence"],
                       module_pin_id=item["module_pin_id"], module_pin_evidence=item["module_pin_evidence"],
                       wire_color=dict(name=item["color"], visibility=item["color_visibility"], evidence=item["evidence"]),
                       evidence=item["evidence"], box=None)
            if role != "component_header":
                row["contact"] = "uncertain"
                row["pin_seat"] = dict(image_id=role, row=PINS[item["pin_id"]]["design_row"], column=6,
                    base_box=[.1, .2, .2, .3], orientation_anchor="Visible board corner and header end.",
                    count_evidence="Sixth column from identified end, including empty positions.",
                    capture_id=slots[role]["capture_id"], source_sha256=slots[role]["sha256"], source_size=[4000, 3000])
            connectors.append(row)
        views.append(dict(role=role, connectors=connectors, limitations=""))
    opinion = ReviewOpinion(views=views, wire_paths=[])
    review = dict(slots=slots)
    found = _canonical_candidates(opinion, review, PINS, {"SIGNAL_A", "SIGNAL_B"})
    assert all(item["pin_id"] for item in found if item["role"] != "component_header")
    assert all(row["diagnosis"]["status"] == "suspected" for row in compare(found))
    changed = deepcopy(review)
    changed["slots"]["pi_side_a"]["capture_id"] = "new-photo"
    stale = _canonical_candidates(opinion, changed, PINS, {"SIGNAL_A", "SIGNAL_B"})
    assert all(item["pin_id"] is None and item["pin_seat"] is None for item in stale if item["role"] != "component_header")
    assert_uncertain(compare(stale))
