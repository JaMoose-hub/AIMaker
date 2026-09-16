import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('evidence_recorder',
    Path(__file__).resolve().parents[2]/'tools/record_tracking_evidence.py')
recorder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


def test_gaps_are_reported_not_interpolated():
    assert recorder.summarize([{'frame_id':i} for i in [1,2,5]]) == {
        'frames':3,'nonmonotonic':0,'skipped_frame_ids':2,'max_frame_id_gap':3}


@pytest.mark.parametrize('model',[True,False])
def test_mismatched_images_are_rejected(model):
    packet={'frame_id':1,'component_pose':{'frame_id':2},
            'detection':{'frame_id':1},'components':[{'frame_id':2}]}
    with pytest.raises(ValueError): recorder.validate(packet,model)


def test_matching_pair_accepted():
    recorder.validate({'frame_id':7,'component_pose':{'frame_id':7}},True)
