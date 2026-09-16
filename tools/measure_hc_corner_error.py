"""Visible-corner review metrics; missing poses are not counted as zero error."""
import argparse
import json
from pathlib import Path
import numpy as np


def corner_errors(label, candidate):
    if candidate is None:
        return []
    q=np.asarray(candidate,dtype=float)
    if q.shape != (4,2) or not np.isfinite(q).all():
        return []
    return [float(np.linalg.norm(q[i]-point)) for i,point in enumerate(label) if point is not None]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    labels=json.loads((args.folder/'pcb-review-labels.json').read_text())
    raw=json.loads((args.folder/'raw-observations.json').read_text())
    before={r['frame_id']:r for r in json.loads(args.before.read_text())['results']}
    after={r['frame_id']:r for r in json.loads(args.after.read_text())['results']}
    samples=[];errors={k:[] for k in ('model','reference','before_locked','after_locked')}
    coverage={k:0 for k in errors}
    for row in labels['frames']:
        fid=row['frame_id']
        result=after.get(fid,{})
        candidates={'model':raw[str(fid)]['corners'],
                    'reference':result.get('input_corners') if result.get('input_source')=='hc_reference_sift' else None}
        for key,results in [('before_locked',before),('after_locked',after)]:
            result=results.get(fid,{})
            candidates[key]=result.get('outline') if result.get('tracking')=='locked' else None
        sample={'frame_id':fid,'annotation_note':row.get('note')}
        for key,q in candidates.items():
            values=corner_errors(row['corners'],q)
            errors[key].extend(values)
            coverage[key]+=bool(values)
            sample[key]={'visible_corner_errors_px':values,'available':bool(values)}
        samples.append(sample)
    summary={k:{'labeled_frames_with_pose':coverage[k],'visible_corners':len(v),
                'mean_error_px':round(float(np.mean(v)),1) if v else None,
                'max_error_px':round(float(np.max(v)),1) if v else None} for k,v in errors.items()}
    common=[]
    for row in labels['frames']:
        fid=row['frame_id'];b=before[fid];a=after[fid]
        if b['tracking']==a['tracking']=='locked':
            common.append({'frame_id':fid,'before':corner_errors(row['corners'],b['outline']),
                           'after':corner_errors(row['corners'],a['outline'])})
    report={'summary':summary,'samples':samples,'paired_locked_comparison':common,
        'annotation_method':labels['method'],
        'limitation':f"{len(labels['frames'])} selected review frames with roughly 5px visual label uncertainty (see per-frame blur notes); differing coverage prevents treating aggregate means as a paired improvement. Not training or GPIO ground truth."}
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
