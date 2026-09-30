from pathlib import Path
import sys
import json

import cv2
import numpy as np
import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

from wiring_pose_data import (read_label, label_text, transform_label, targeted_image,
                              quarantine_cross_split, balanced_indices, apply_semantic_quarantine)
from wiring_pose_evaluation import cache_signature, j8_errors, summarize, gate, compare_tensors, box_iou,quad_iou
from wiring_pose_experiment import choose_checkpoint, train_one, audit_finetune_learning_rates
from wiring_pose_replay import temporal_summary, report as build_report
from wiring_pose_data import write_json
from wiring_pose_candidates import orientation_consensus
from wiring_pose_followup_finalize import choose_localization_checkpoint,temporal_comparison
from dataclasses import dataclass,replace


@dataclass
class OrientationObservation:
    corners_px: np.ndarray


def test_tft_glass_border_cannot_reverse_header_identity():
    obs=OrientationObservation(np.array([[0,0],[100,0],[100,180],[0,180]],float))
    def incorrect(frame,observation,evidence):
        evidence.update(verified=True,corrected=True,top_inset=.0913,bottom_inset=.0411)
        return replace(observation,corners_px=np.roll(observation.corners_px,2,axis=0))
    evidence={}
    assert orientation_consensus(incorrect)(None,obs,evidence) is obs
    assert not evidence["verified"]


def test_consistent_active_lcd_can_still_correct_reversed_header():
    obs=OrientationObservation(np.array([[0,0],[100,0],[100,180],[0,180]],float))
    def supported(frame,observation,evidence):
        evidence.update(verified=True,corrected=True,top_inset=.15,bottom_inset=.07)
        return replace(observation,corners_px=np.roll(observation.corners_px,2,axis=0))
    evidence={}
    result=orientation_consensus(supported)(None,obs,evidence)
    np.testing.assert_array_equal(result.corners_px,np.roll(obs.corners_px,2,axis=0))
    assert evidence["verified"] and evidence["orientation_consensus"]["support"]==4


def test_actual_localization_goal_is_not_sacrificed_for_minimum_misses():
    baseline={"missed":8,"false_positive":0,"raw_corner_diagonal":{"p95":1.}}
    candidates=[{"epoch":1,"misses":0,"false_positives":0,"normalized":{"p95":.9}},
                {"epoch":2,"misses":2,"false_positives":0,"normalized":{"p95":.8}},
                {"epoch":3,"misses":9,"false_positives":0,"normalized":{"p95":.4}}]
    assert choose_localization_checkpoint(candidates,baseline)["epoch"]==2


def test_replay_report_rejects_missing_repeat_instead_of_truncating():
    with pytest.raises(ValueError,match="repeat count"):
        temporal_comparison([{"repeat":0}],[])


def test_replay_report_rejects_different_source_sequence():
    with pytest.raises(ValueError,match="identity"):
        temporal_comparison([{"repeat":0,"sequences":[{"sequence":"first"}]}],
                            [{"repeat":0,"sequences":[{"sequence":"other"}]}])


def test_wrong_object_post_geometry_is_not_valid_coverage():
    quad=[[0,0],[10,0],[10,10],[0,10]]
    far=(np.array(quad)+100).tolist()
    record={"positive":True,"raw_detected":True,"matched_detection":False,"tracking":"searching",
            "post_corner_px":[100]*4,"post_corners":far,"truth_corners":quad}
    summary=summarize([record])
    assert summary["post_emitted_positive"]==1 and summary["post_localized_positive"]==0
    assert quad_iou(quad,quad)==1 and quad_iou(quad,far)==0
    assert quad_iou(np.zeros((4,2)),quad)==0


def test_tft_orientation_flip_needs_consistent_current_image_support():
    obs=OrientationObservation(np.array([[0,0],[100,0],[100,180],[0,180]],float))
    def brittle(frame,observation,evidence):
        supported=bool(np.all(observation.corners_px==obs.corners_px))
        evidence.update(verified=supported,corrected=supported,top_inset=.15,bottom_inset=.07)
        return replace(observation,corners_px=np.roll(observation.corners_px,2,axis=0)) if supported else observation
    evidence={}
    assert orientation_consensus(brittle)(None,obs,evidence) is obs
    assert evidence["reason"]=="unstable_lcd_orientation"


def pose():
    return np.array([0,.5,.5,.8,.8,.1,.1,2,.9,.1,2,.9,.9,2,.1,.9,2],float)


def test_missing_annotation_is_not_a_negative(tmp_path):
    path=tmp_path/"missing.txt"
    with pytest.raises(ValueError,match="missing_label"):read_label(path)
    path.write_text("")
    assert read_label(path) is None


@pytest.mark.parametrize("value", [.1, .0669, float("nan"), float("inf"), -.0001])
def test_fine_tuning_rejects_high_bias_warmup_and_invalid_rates(value):
    with pytest.raises(ValueError,match="budget"):
        audit_finetune_learning_rates([{"lr/pg0":.0001,"lr/pg1":value}],.0001)


def test_fine_tuning_records_all_optimizer_group_maxima():
    rows=[{"lr/pg0":.00005,"lr/pg1":.00006},{"lr/pg0":.0001,"lr/pg1":.00008}]
    assert audit_finetune_learning_rates(rows,.0001)=={"lr/pg0":.0001,"lr/pg1":.00008}


@pytest.mark.parametrize("text", ["0 nan .5 .8 .8", "0 .5 .5 .8 .8", "1 "+" ".join(map(str,pose()[1:]))])
def test_invalid_annotations_rejected(tmp_path,text):
    path=tmp_path/"label.txt"
    path.write_text(text)
    with pytest.raises(ValueError):read_label(path)


def test_crossed_semantic_corners_are_rejected(tmp_path):
    values=pose()
    points=values[5:].reshape(4,3)
    points[[1,2]]=points[[2,1]]
    path=tmp_path/"label.txt"
    path.write_text(label_text(values))
    with pytest.raises(ValueError,match="crossed"):read_label(path)


def test_geometry_moves_box_and_keypoints_together():
    matrix=np.array([[.5,0,25],[0,.5,25],[0,0,1]],np.float32)
    result=transform_label(pose(),matrix,100,100)
    assert np.allclose(result[1:5],[.5,.5,.4,.4])
    assert np.allclose(result[5:].reshape(4,3)[:,:2],[[.3,.3],[.7,.3],[.7,.7],[.3,.7]])
    assert np.all(result[5:].reshape(4,3)[:,2]==2)


def test_outside_points_lose_visibility_and_negatives_stay_empty():
    matrix=np.array([[1,0,50],[0,1,0],[0,0,1]],np.float32)
    result=transform_label(pose(),matrix,100,100)
    assert result[5:].reshape(4,3)[1,2]==0
    assert transform_label(None,matrix,100,100) is None


def test_tft_content_does_not_touch_mounting_holes_or_border():
    frame=np.full((200,300,3),80,np.uint8)
    result,values,meta=targeted_image(frame,pose(),"tft",np.random.default_rng(0))
    assert np.array_equal(values,pose())
    assert np.array_equal(result[:40],frame[:40])
    assert np.array_equal(result[:, :60],frame[:,:60])
    assert np.any(result!=frame)
    assert meta["board_covered_fraction"] < .40


def test_pi_occlusion_never_exceeds_twenty_percent():
    frame=np.full((200,300,3),80,np.uint8)
    for seed in range(25):
        result,values,meta=targeted_image(frame,pose(),"pi",np.random.default_rng(seed))
        assert meta["board_covered_fraction"]<=.20
        assert np.allclose(values[5:].reshape(4,3)[:,:2],pose()[5:].reshape(4,3)[:,:2])
        assert np.isin(values[5:].reshape(4,3)[:,2],[1,2]).all()


def test_training_capture_group_cannot_cross_validation():
    rows=[{"split":"train","sha256":"a","group":"one","derived":False,"eligible_train":True,"original_image":"a"},
          {"split":"val","sha256":"b","group":"one","derived":False,"eligible_train":False,"original_image":"b"}]
    issues=quarantine_cross_split(rows)
    assert len(issues)==1 and not rows[0]["eligible_train"]


def test_balancing_is_group_equal_and_reproducible():
    rows=[{"group":"a"} for _ in range(3)]+[{"group":"b"}]
    first=balanced_indices(rows)
    assert first==balanced_indices(rows)
    assert sum(rows[i]["group"]=="a" for i in first)==3
    assert sum(rows[i]["group"]=="b" for i in first)==3


def test_cache_identity_includes_weights_inputs_runtime_and_thresholds():
    base=cache_signature("a","image",{"conf":.3},"runtime")
    assert base!=cache_signature("b","image",{"conf":.3},"runtime")
    assert base!=cache_signature("a","other",{"conf":.3},"runtime")
    assert base!=cache_signature("a","image",{"conf":.2},"runtime")
    assert base!=cache_signature("a","image",{"conf":.3},"new-runtime")


def test_j8_uses_four_independently_annotated_endpoints():
    truth=[[.1,.1,2],[.1,.2,2],[.9,.2,2],[.9,.1,2]]
    pins={"3V3_P1":[11,10],"5V_P2":[11,20],"GPIO21":[91,20],"GND_P39":[91,10]}
    error=j8_errors(pins,truth,100,100)
    assert len(error["px"])==4
    assert np.allclose(error["px"],1)
    assert np.allclose(error["pitch"],.1)


def test_missing_predictions_remain_in_localization_denominator():
    rows=[{"positive":True,"raw_detected":True,"raw_localization_pass":True,"tracking":"locked"},
          {"positive":True,"raw_detected":False,"tracking":"searching"},
          {"positive":False,"raw_detected":True,"tracking":"locked"}]
    report=summarize(rows)
    assert report["missed"]==1 and report["false_positive"]==1
    assert report["raw_localization_success"]==.5


def test_error_reduction_cannot_hide_additional_misses():
    base={"component":"pi","summary":{"missed":0,"false_positive":0,"negative":2,
          "raw_localization_success":.5,"raw_j8_pitch":{"p95":1.}}}
    candidate={"component":"pi","summary":{**base["summary"],"missed":1,"raw_j8_pitch":{"p95":.5}}}
    result=gate(base,candidate)
    assert not result["regression_gate_passed"]
    assert not result["production_promotion"]


def test_better_raw_model_cannot_hide_worse_production_geometry():
    summary={"missed":0,"false_positive":0,"negative":2,"raw_localization_success":.5,
             "raw_j8_pitch":{"p95":1.},"runtime_j8_pitch":{"p95":1.},"post_localized_positive":8}
    base={"component":"pi","summary":summary}
    candidate={"component":"pi","summary":{**summary,"raw_j8_pitch":{"p95":.7},"runtime_j8_pitch":{"p95":1.2}}}
    assert not gate(base,candidate)["regression_gate_passed"]
    candidate["summary"]["runtime_j8_pitch"]={"p95":.8}
    assert gate(base,candidate)["regression_gate_passed"]
    candidate["summary"]["post_localized_positive"]=7
    assert not gate(base,candidate)["regression_gate_passed"]


def test_checkpoint_selection_respects_common_budget_and_breaks_plateau(tmp_path):
    (tmp_path/"weights").mkdir()
    for index in range(4):(tmp_path/"weights"/f"epoch{index}.pt").touch()
    (tmp_path/"results.csv").write_text("metrics/mAP50-95(P),val/pose_loss\n.99,.3\n.99,.2\n.99,.1\n1,.01\n")
    path,epoch=choose_checkpoint(tmp_path,2)
    assert epoch==2 and path.name=="epoch1.pt"


def test_sparse_frames_do_not_claim_precise_recovery():
    rows=[{"tracking":state,"ts_ms":t,"current_observation":True} for state,t in
          [("locked",0),("searching",750),("locked",1500)]]
    assert temporal_summary(rows,False)["observed_relock_ms"] is None
    assert temporal_summary(rows,True)["observed_relock_ms"]["median"]==750


def test_stale_lock_is_not_counted_as_current_observation():
    rows=[{"tracking":"locked","ts_ms":0,"current_observation":False}]
    result=temporal_summary(rows,True)
    assert result["locked_with_current_observation"]==0
    assert result["static_ground_truth_jitter"] is None


def test_hc_glare_preserves_labels_and_occlusion_cap():
    frame=np.full((200,300,3),80,np.uint8)
    image,label,metadata=targeted_image(frame,pose(),"hc",np.random.default_rng(3))
    assert np.any(image!=frame)
    assert metadata["board_covered_fraction"]<=.20
    assert np.allclose(label[5:].reshape(4,3)[:,:2],pose()[5:].reshape(4,3)[:,:2])


@pytest.mark.parametrize("actual",[np.ones((2,3)),np.full((2,2),np.nan),np.full((2,2),2.)])
def test_pt_onnx_parity_rejects_shape_nonfinite_and_value_mismatch(actual):
    assert not compare_tensors(np.ones((2,2)),actual)["allclose"]


def test_pt_onnx_parity_accepts_documented_float_tolerance():
    assert compare_tensors(np.ones((2,2)),np.ones((2,2))+.001)["allclose"]


def test_semantic_quarantine_is_bound_to_exact_image_and_label_hashes(tmp_path):
    rule=json.loads((TOOLS/"wiring_pose_semantic_exclusions.json").read_text(encoding="utf-8"))["tft"]
    image,label=rule["anchors"][0]
    rows=[{"sha256":image,"label_sha256":"changed","key":"corrected"}]
    apply_semantic_quarantine(tmp_path,{"components":{"tft":{"records":rows}}})
    assert not (tmp_path/"blocked/tft.json").exists()
    rows[0]["label_sha256"]=label
    apply_semantic_quarantine(tmp_path,{"components":{"tft":{"records":rows}}})
    assert (tmp_path/"blocked/tft.json").exists()


def test_quarantined_component_cannot_start_training(tmp_path):
    (tmp_path/"blocked").mkdir()
    (tmp_path/"blocked/tft.json").write_text("{}")
    with pytest.raises(RuntimeError,match="quarantined"):
        train_one(tmp_path,"tft","A",0)
    assert not (tmp_path/"training").exists()


def test_predicting_the_wrong_object_is_a_miss():
    assert box_iou([0,0,10,10],[20,20,30,30])==0
    assert box_iou([0,0,10,10],[0,0,10,10])==1
    summary=summarize([{"positive":True,"raw_detected":True,"matched_detection":False,"tracking":"searching"}])
    assert summary["detected"]==0 and summary["missed"]==1
    assert summary["wrong_object_predictions"]==1


def test_report_does_not_claim_all_training_finished_when_one_class_is_quarantined(tmp_path):
    components={c:{"counts":{"train_original_eligible":20,"val":5,"j8_validation":0},"active":"base"} for c in ("pi","tft","hc")}
    write_json(tmp_path/"manifest.json",{"components":components,"frozen_files":[]})
    write_json(tmp_path/"blocked/tft.json",{"reason":"fixture semantic conflict"})
    for c in ("pi","hc"):
        write_json(tmp_path/"selection"/(c+".json"),{"candidate":{"arm":"A","name":c+"-A-seed0"}})
        for seed in (0,1):
            write_json(tmp_path/"candidates"/f"{c}-A-seed{seed}"/"gate.json",{"regression_gate_passed":False,"p95_improvement":.1})
            training=tmp_path/"training"/f"{c}-A-seed{seed}"
            training.mkdir(parents=True)
            (training/"results.csv").write_text(f"epoch,time,loss\n1,1,{seed+1}\n")
    result=build_report(tmp_path)
    assert not result["planned_training_complete"]
    assert result["blocked_components"]==["tft"]
    assert result["components"]["pi"]["different_seed_effect_verified"]
    assert not result["speed_gate"]
    assert "fixture semantic conflict" in (tmp_path/"REPORT.md").read_text(encoding="utf-8")
