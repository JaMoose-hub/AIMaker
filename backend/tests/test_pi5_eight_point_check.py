from pathlib import Path
import sys
import json

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools"))
from pi5_eight_point_check import header_shape,summary
from pi5_eight_point_finish import qualification,paired_still_comparison


def rectangle():
    return np.array([[0.,0.],[0.,10.],[190.,10.],[190.,0.]])


def test_header_angle_is_translation_invariant_but_not_rotation_invariant():
    truth=rectangle()
    assert header_shape(truth+5,truth)["row_angle_deg"]==[0.,0.]
    angle=np.radians(8)
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    np.testing.assert_allclose(header_shape(truth@rotation.T,truth)["row_angle_deg"],[8,8])


def test_header_reversed_rows_and_crossings_are_flagged():
    truth=rectangle()
    assert header_shape(truth[[1,0,3,2]],truth)["crossed_or_reversed"]
    assert header_shape(truth[[0,2,1,3]],truth)["crossed_or_reversed"]
    assert header_shape(np.full((4,2),np.nan),truth) is None


def test_endpoint_summary_preserves_misses_and_is_json_serializable():
    metric={"px":[0.]*4,"pitch":[0.]*4,**header_shape(rectangle(),rectangle())}
    result=summary([{"positive":True,"matched":True,"raw":metric},
                    {"positive":True,"matched":False},
                    {"positive":False,"detected":True}])
    assert result["positive"]==2 and result["misses"]==1 and result["false_positive"]==1
    assert result["stages"]["raw"]["successful_frames"]==1
    json.dumps(result,allow_nan=False)


def test_better_endpoint_distance_cannot_hide_a_more_tilted_gpio_row():
    def stage(error,angle):
        return {"frames":35,"px":{"p95":error},"pitch":{"p95":error},
                "row_angle_deg":{"p95":angle},"crossed_or_reversed":0}
    baseline={"misses":0,"false_positive":0,"stages":{"runtime":stage(1.,2.)}}
    candidate={"misses":0,"false_positive":0,"stages":{"raw":stage(.7,3.),"runtime":stage(.7,1.5)}}
    result=qualification(baseline,candidate,{"pi":{"per_clip_not_worse":True}},True,True)
    assert not result["offline_gate_passed"]
    assert not result["checks"]["direct_eight_angle_not_worse"]
    assert not result["production_promotion"]


def test_static_improvement_cannot_hide_failed_continuous_replay():
    stage=lambda value:{"frames":35,"px":{"p95":value},"pitch":{"p95":value},
                        "row_angle_deg":{"p95":value},"crossed_or_reversed":0}
    base={"misses":0,"false_positive":0,"stages":{"runtime":stage(1.)}}
    candidate={"misses":0,"false_positive":0,"stages":{"runtime":stage(.5),"raw":stage(.5)}}
    assert not qualification(base,candidate,{"pi":{"per_clip_not_worse":False}},True,True)["offline_gate_passed"]


def test_paired_metrics_use_identical_images_not_different_output_subsets():
    metric=lambda value:{"px":[value]*4,"pitch":[value]*4,"row_angle_deg":[value]*2}
    base={"records":[{"key":"a","positive":True,"runtime":metric(2)},
                     {"key":"b","positive":True,"runtime":metric(10)}]}
    candidate={"records":[{"key":"a","positive":True,"runtime":metric(3),"raw":metric(1)},
                          {"key":"b","positive":True,"raw":metric(1)}]}
    result=paired_still_comparison(base,candidate)
    assert result["runtime"]["paired_images"]==1
    assert result["runtime"]["four_final"]["px"]["p95"]==2
    assert result["runtime"]["eight_runtime"]["px"]["p95"]==3
    assert result["raw"]["paired_images"]==2
