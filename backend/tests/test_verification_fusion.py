from __future__ import annotations

from app.verification.fusion import fuse_evidence
from app.verification.models import VerificationEvidence
from app.verification.state import VerificationState


NOW = 1_000.0


def _evidence(source, status, score=0.0, reason="test", *, fresh=2_000.0):
    return VerificationEvidence(
        source=source,
        status=status,
        score=score,
        quality=1.0,
        reason=reason,
        as_of_ms=NOW,
        fresh_until_ms=fresh,
        method="test",
    )


def test_geometry_only_is_capped_below_visual_verification():
    result = fuse_evidence({"geometry": _evidence("geometry", "pass", 0.96)}, now_ms=NOW)
    assert result.verdict == "position_matched"
    assert result.verification_level == "geometry"
    assert result.overall_confidence == 49
    assert result.score_cap == 49


def test_visual_only_progress_is_nonzero_but_capped_below_geometry():
    result = fuse_evidence(
        {"visual": _evidence("visual", "pass", 0.86)},
        now_ms=NOW,
    )
    assert result.verdict == "evidence_incomplete"
    assert result.verification_level == "visual"
    assert result.overall_confidence == 39
    assert result.score_cap == 39
    assert result.reason == "visual_pass_geometry_incomplete"


def test_correlated_camera_layers_are_harmonic_and_capped_at_79():
    result = fuse_evidence(
        {
            "geometry": _evidence("geometry", "pass", 0.92),
            "visual": _evidence("visual", "pass", 0.86),
        },
        now_ms=NOW,
    )
    assert result.verdict == "visual_verified"
    assert result.overall_confidence == 79
    assert result.reason == "electrical_not_available"


def test_all_three_layers_produce_full_verified_score():
    result = fuse_evidence(
        {
            "geometry": _evidence("geometry", "pass", 0.92),
            "visual": _evidence("visual", "pass", 0.86),
            "electrical": _evidence("electrical", "pass", 0.94),
        },
        now_ms=NOW,
    )
    assert result.verdict == "verified"
    assert result.verification_level == "electrical"
    assert result.overall_confidence == 92
    assert result.score_cap == 99


def test_guided_vlm_and_serial_can_pass_without_geometry():
    result = fuse_evidence(
        {
            "geometry": _evidence(
                "geometry", "unavailable", 0.0, "geometry_skipped_for_vlm"
            ),
            "visual": _evidence("visual", "pass", 0.86),
            "electrical": _evidence("electrical", "pass", 0.94),
        },
        now_ms=NOW,
    )
    assert result.verdict == "verified"
    assert result.verification_level == "electrical"
    assert result.reason == "visual_and_electrical_passed_geometry_skipped"
    assert result.score_cap == 95


def test_final_vlm_result_is_promoted_into_fusion_and_survives_roi_updates():
    state = VerificationState()
    state.set_step(
        "photoresistor-ao",
        "A0",
        "AO",
        "photoresistor-module",
        electrical_available=True,
    )
    connections = [
        {"board_pin": "3V3", "component_pin": "VCC", "state": "inserted_target", "confidence": 0.95},
        {"board_pin": "GND", "component_pin": "GND", "state": "inserted_target", "confidence": 0.95},
        {"board_pin": "A0", "component_pin": "AO", "state": "inserted_target", "confidence": 0.85},
    ]
    assert state.set_final_visual_pending("photoresistor-ao", now_ms=NOW) is True
    assert state.set_final_visual_result(
        "photoresistor-ao", connections, now_ms=NOW + 1
    ) is True
    state.request_electrical("photoresistor-ao")
    state.update(
        "photoresistor-ao",
        [_evidence("electrical", "pass", 0.94, fresh=0.0)],
        now_ms=NOW + 2,
    )
    state.update(
        "photoresistor-ao",
        [
            VerificationEvidence.uncertain(
                "visual",
                "waiting_for_both_endpoints",
                method="guided_roi",
                as_of_ms=NOW + 3,
            )
        ],
        now_ms=NOW + 3,
    )
    snapshot = state.snapshot(NOW + 100_000)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_final_wiring"
    assert snapshot["evidence"]["visual"]["status"] == "pass"
    assert snapshot["fusion"]["verdict"] == "verified"
    assert snapshot["fusion"]["overall_confidence"] > 0


def test_final_vlm_adjacent_pin_is_a_visual_failure():
    state = VerificationState()
    state.set_step("photoresistor-ao", "A0", "AO", "photoresistor-module")
    assert state.set_final_visual_result(
        "photoresistor-ao",
        [
            {"board_pin": "3V3", "component_pin": "VCC", "state": "inserted_target", "confidence": 0.95},
            {"board_pin": "GND", "component_pin": "GND", "state": "inserted_target", "confidence": 0.95},
            {"board_pin": "A0", "component_pin": "AO", "state": "inserted_adjacent", "confidence": 0.85},
        ],
        now_ms=NOW,
    ) is True
    snapshot = state.snapshot(NOW)
    assert snapshot["evidence"]["visual"]["status"] == "uncertain"
    assert snapshot["evidence"]["visual"]["score"] == 0.8
    assert snapshot["evidence"]["visual"]["reason"] == "final_wiring_adjacent_pin"
    assert snapshot["fusion"]["overall_confidence"] == 59


def test_final_vlm_partial_visual_and_serial_add_progress_without_passing():
    result = fuse_evidence(
        {
            "geometry": _evidence(
                "geometry", "unavailable", 0.0, "geometry_skipped_for_vlm"
            ),
            "visual": VerificationEvidence(
                source="visual",
                status="uncertain",
                score=0.8,
                quality=0.9,
                reason="final_wiring_adjacent_pin",
                method="vlm_final_wiring",
                details={"partial": True},
            ),
            "electrical": _evidence("electrical", "pass", 0.95),
        },
        now_ms=NOW,
    )
    assert result.verdict == "evidence_incomplete"
    assert result.overall_confidence == 79
    assert result.score_cap == 79
    assert result.reason == "electrical_pass_visual_partial"


def test_focus_loss_resets_guided_vlm_and_serial_score_to_zero():
    result = fuse_evidence(
        {
            "geometry": _evidence(
                "geometry", "unavailable", 0.0, "geometry_skipped_for_vlm"
            ),
            "visual": _evidence("visual", "uncertain", 0.0, "component_not_tracked"),
            "electrical": _evidence("electrical", "pass", 0.94),
        },
        now_ms=NOW,
    )
    assert result.verdict == "evidence_incomplete"
    assert result.overall_confidence == 0
    assert result.score_cap == 0
    assert result.reason == "visual_focus_lost"


def test_electrical_failure_is_not_averaged_away_by_camera_passes():
    result = fuse_evidence(
        {
            "geometry": _evidence("geometry", "pass", 0.95),
            "visual": _evidence("visual", "pass", 0.90),
            "electrical": _evidence("electrical", "fail", 0.96, "no_a0_response"),
        },
        now_ms=NOW,
    )
    assert result.verdict == "evidence_conflict"
    assert result.overall_confidence <= 4
    assert result.verdict_confidence == 96


def test_electrical_pass_does_not_lower_visual_failure_score():
    result = fuse_evidence(
        {
            "geometry": _evidence(
                "geometry", "unavailable", 0.0, "geometry_skipped_for_vlm"
            ),
            "visual": _evidence("visual", "fail", 0.75, "final_wiring_adjacent_pin"),
            "electrical": _evidence("electrical", "pass", 0.92),
        },
        now_ms=NOW,
    )
    assert result.verdict == "evidence_conflict"
    assert result.overall_confidence == 20
    assert result.verdict_confidence == 75
    assert result.reason == "electrical_pass_but_visual_failed"


def test_wrong_pin_is_a_hard_failure():
    result = fuse_evidence(
        {"geometry": _evidence("geometry", "fail", 0.91, "wrong_pin")},
        now_ms=NOW,
    )
    assert result.verdict == "wrong_pin"
    assert result.overall_confidence == 9


def test_stale_pass_downgrades_to_uncertain_instead_of_staying_green():
    result = fuse_evidence(
        {"geometry": _evidence("geometry", "pass", 0.95, fresh=NOW + 10)},
        now_ms=NOW + 20,
    )
    assert result.verdict == "uncertain"
    assert result.overall_confidence == 0
    assert result.reason == "stale_evidence"


def test_state_drops_updates_for_a_replaced_step_and_serializes_message():
    state = VerificationState()
    state.set_step("step-a", "A0", "AO", "photoresistor-module")
    state.set_step("step-b", "3V3", "VCC", "photoresistor-module")
    assert state.update("step-a", [_evidence("geometry", "pass", 0.9)], now_ms=NOW) is False
    assert state.update("step-b", [_evidence("geometry", "pass", 0.9)], now_ms=NOW) is True
    message = state.message("arduino-uno-q", 7, NOW)
    assert message is not None
    assert message["type"] == "verification_update"
    assert message["target"]["board_pin"] == "3V3"
    assert message["fusion"]["verdict"] == "position_matched"


def test_completed_vlm_snapshot_is_latched_until_explicit_recheck():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    vlm = VerificationEvidence(
        source="visual",
        status="pass",
        score=0.84,
        quality=0.9,
        reason="vlm_both_endpoints_inserted",
        as_of_ms=NOW,
        fresh_until_ms=0.0,
        method="vlm_insertion",
    )
    unchanged = VerificationEvidence.uncertain(
        "visual",
        "waiting_for_both_endpoints",
        as_of_ms=NOW + 10,
        fresh_until_ms=NOW + 1010,
        method="guided_roi",
    )
    state.update("step-vcc", [vlm], now_ms=NOW)
    state.update("step-vcc", [unchanged], now_ms=NOW + 10)
    snapshot = state.snapshot(NOW + 10)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_insertion"
    assert snapshot["fusion"]["overall_confidence"] == 79

    moving = VerificationEvidence.uncertain(
        "visual",
        "scene_moving",
        as_of_ms=NOW + 20,
        fresh_until_ms=NOW + 1020,
        method="guided_roi",
    )
    state.update("step-vcc", [moving], now_ms=NOW + 20)
    snapshot = state.snapshot(NOW + 20)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_insertion"
    assert snapshot["evidence"]["visual"]["reason"] == "vlm_both_endpoints_inserted"
    assert state.snapshot(NOW + 60_000)["fusion"]["overall_confidence"] == 79


def test_component_tracking_dropout_does_not_change_completed_vlm_result():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    vlm = VerificationEvidence(
        source="visual",
        status="pass",
        score=0.78,
        quality=0.85,
        reason="vlm_connectors_seated_pin_uncertain",
        as_of_ms=NOW,
        fresh_until_ms=NOW + 1000,
        method="vlm_insertion",
    )
    dropout = VerificationEvidence.uncertain(
        "visual",
        "component_not_tracked",
        as_of_ms=NOW + 10,
        fresh_until_ms=NOW + 1010,
        method="guided_roi",
    )
    state.update("step-vcc", [vlm], now_ms=NOW)
    state.update("step-vcc", [dropout], now_ms=NOW + 10)
    snapshot = state.snapshot(NOW + 10)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_insertion"
    assert snapshot["evidence"]["visual"]["reason"] == "vlm_connectors_seated_pin_uncertain"
    assert "details" not in snapshot["evidence"]["visual"]
    assert snapshot["fusion"]["overall_confidence"] == 78


def test_board_tracking_dropout_does_not_change_completed_vlm_result():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    vlm = VerificationEvidence(
        source="visual",
        status="pass",
        score=0.78,
        quality=0.85,
        reason="vlm_connectors_seated_pin_uncertain",
        as_of_ms=NOW,
        fresh_until_ms=NOW + 1000,
        method="vlm_insertion",
    )
    dropout = VerificationEvidence.uncertain(
        "visual",
        "board_not_tracked",
        as_of_ms=NOW + 10,
        fresh_until_ms=NOW + 1010,
        method="guided_roi",
    )
    state.update("step-vcc", [vlm], now_ms=NOW)
    state.update("step-vcc", [dropout], now_ms=NOW + 10)
    snapshot = state.snapshot(NOW + 10)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_insertion"
    assert "details" not in snapshot["evidence"]["visual"]
    assert snapshot["fusion"]["overall_confidence"] == 78


def test_small_registered_webcam_noise_does_not_erase_fresh_vlm_result():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    vlm = VerificationEvidence(
        source="visual",
        status="pass",
        score=0.78,
        quality=0.85,
        reason="vlm_connectors_seated_pin_uncertain",
        as_of_ms=NOW,
        fresh_until_ms=NOW + 1000,
        method="vlm_insertion",
    )
    webcam_noise = VerificationEvidence.uncertain(
        "visual",
        "scene_moving",
        as_of_ms=NOW + 10,
        fresh_until_ms=NOW + 1010,
        method="guided_roi",
        details={
            "board_change": 0.22,
            "component_change": 0.09,
            "preview_stable_hits": 8,
        },
    )
    state.update("step-vcc", [vlm], now_ms=NOW)
    state.update("step-vcc", [webcam_noise], now_ms=NOW + 10)
    assert state.snapshot(NOW + 10)["evidence"]["visual"]["method"] == "vlm_insertion"


def test_large_scene_change_does_not_erase_completed_vlm_result():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    vlm = VerificationEvidence(
        source="visual",
        status="pass",
        score=0.78,
        quality=0.85,
        reason="vlm_connectors_seated_pin_uncertain",
        as_of_ms=NOW,
        fresh_until_ms=NOW + 1000,
        method="vlm_insertion",
    )
    moved = VerificationEvidence.uncertain(
        "visual",
        "scene_moving",
        as_of_ms=NOW + 10,
        fresh_until_ms=NOW + 1010,
        method="guided_roi",
        details={
            "board_change": 0.48,
            "component_change": 0.12,
            "preview_stable_hits": 8,
        },
    )
    state.update("step-vcc", [vlm], now_ms=NOW)
    state.update("step-vcc", [moved], now_ms=NOW + 10)
    snapshot = state.snapshot(NOW + 10)
    assert snapshot["evidence"]["visual"]["method"] == "vlm_insertion"
    assert snapshot["evidence"]["visual"]["reason"] == "vlm_connectors_seated_pin_uncertain"


def test_enabled_serial_reports_non_a0_step_as_not_applicable():
    state = VerificationState()
    state.set_step(
        "step-vcc",
        "3V3",
        "VCC",
        "photoresistor-module",
        electrical_unavailable_reason="electrical_not_applicable",
    )
    snapshot = state.snapshot(NOW)
    assert snapshot["evidence"]["electrical"]["reason"] == "electrical_not_applicable"


def test_a0_electrical_challenge_waits_for_explicit_request_and_can_restart():
    state = VerificationState()
    state.set_step(
        "step-a0",
        "A0",
        "AO",
        "photoresistor-module",
        electrical_available=True,
    )
    before = state.snapshot(NOW)
    assert before["target"]["electrical_supported"] is True
    assert before["target"]["electrical_requested"] is False
    assert before["evidence"]["electrical"]["reason"] == "awaiting_electrical_start"

    assert state.request_electrical("step-a0") is True
    first = state.snapshot(NOW)
    assert first["target"]["electrical_requested"] is True
    assert first["target"]["electrical_generation"] == 1
    assert first["evidence"]["electrical"]["reason"] == "collecting_a0_baseline"

    assert state.request_electrical("step-a0") is True
    assert state.snapshot(NOW)["target"]["electrical_generation"] == 2


def test_manual_geometry_freezes_after_three_of_five_pass_observations():
    state = VerificationState()
    state.set_step("step-vcc", "3V3", "VCC", "photoresistor-module")
    before = state.snapshot(NOW)
    assert before["target"]["geometry_requested"] is False
    assert before["evidence"]["geometry"]["reason"] == "geometry_skipped_for_vlm"

    assert state.request_geometry("step-vcc") is True
    observations = [
        _evidence("geometry", "pass", 0.82, "both_endpoints_near_targets"),
        _evidence("geometry", "uncertain", 0.0, "waiting_for_component_endpoint"),
        _evidence("geometry", "pass", 0.80, "both_endpoints_near_targets"),
        _evidence("geometry", "pass", 0.84, "both_endpoints_near_targets"),
        _evidence("geometry", "uncertain", 0.0, "scene_moving"),
    ]
    for frame_id, item in enumerate(observations, start=1):
        assert state.add_geometry_sample(
            "step-vcc", item, frame_id=frame_id, now_ms=NOW + frame_id
        ) is True

    snapshot = state.snapshot(NOW + 10)
    assert snapshot["target"]["geometry_complete"] is True
    assert snapshot["evidence"]["geometry"]["status"] == "pass"
    assert snapshot["evidence"]["geometry"]["method"] == "manual_dual_endpoint_consensus"
    assert snapshot["evidence"]["geometry"]["details"]["pass_count"] == 3
    assert snapshot["evidence"]["geometry"]["details"]["frozen"] is True

    # Once frozen, live observations cannot make the result jump around.
    assert state.add_geometry_sample(
        "step-vcc",
        _evidence("geometry", "fail", 0.95, "wrong_pin"),
        frame_id=6,
        now_ms=NOW + 20,
    ) is False
    assert state.snapshot(NOW + 20)["evidence"]["geometry"]["status"] == "pass"

    assert state.request_geometry("step-vcc") is True
    restarted = state.snapshot(NOW + 30)
    assert restarted["target"]["geometry_generation"] == 2
    assert restarted["target"]["geometry_complete"] is False
    assert restarted["evidence"]["geometry"]["details"]["sample_count"] == 0
