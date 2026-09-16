"""Record paired display frames and independent model-source frames.

Read-only HTTP. No camera controls, new inference, image interpolation or
training-data writes. Latest-only endpoints may skip frames: report gaps.
Model-source poses are postprocessed observations, NOT raw YOLO landmarks.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import httpx


def validate(packet, model=False):
    poses = [packet['component_pose']] if model else [packet['detection'], *packet['components']]
    if any(p['frame_id'] != packet['frame_id'] for p in poses):
        raise ValueError('Image/pose frame mismatch')


def summarize(rows):
    ids = [r['frame_id'] for r in rows]
    gaps = [b-a for a,b in zip(ids,ids[1:])]
    return {'frames':len(ids), 'nonmonotonic':sum(g<=0 for g in gaps),
            'skipped_frame_ids':sum(max(0,g-1) for g in gaps),
            'max_frame_id_gap':max(gaps,default=0)}


def capture(folder, seconds, component, model=False):
    folder.mkdir()
    rows, error = [], None
    after = -1
    deadline = time.monotonic()+seconds
    endpoint = '/api/tracking/component-source' if model else '/api/tracking/frame'
    try:
        with httpx.Client(base_url='http://127.0.0.1:8100',timeout=5) as client:
            with (folder/'frames.jsonl').open('w',encoding='utf-8') as index:
                while time.monotonic()<deadline:
                    params={'after':after}
                    if model: params['component_id']=component
                    response=client.get(endpoint,params=params)
                    if response.status_code==204:
                        time.sleep(.005)
                        continue
                    response.raise_for_status()
                    packet=response.json()
                    validate(packet,model)
                    cursor=packet['frame_id'] if model else packet['seq']
                    if cursor<=after:
                        raise ValueError('Non-increasing source cursor')
                    after=cursor
                    header, encoded=packet.pop('image').split(',',1)
                    extension='png' if 'image/png' in header else 'jpg'
                    filename=f'{packet["frame_id"]}.{extension}'
                    (folder/filename).write_bytes(base64.b64decode(encoded,validate=True))
                    packet['image_path']=filename
                    packet['received_monotonic']=time.monotonic()
                    index.write(json.dumps(packet)+'\n'); index.flush()
                    rows.append(packet)
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
    return {**summarize(rows),'error':error}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=12)
    parser.add_argument('--component',choices=['hc-sr04','mrd-tf240-8p-cs'],default='hc-sr04')
    args=parser.parse_args()
    if not 0<args.seconds<=60: parser.error('Duration must be 0..60 seconds')
    with httpx.Client(base_url='http://127.0.0.1:8100',timeout=5) as client:
        response=client.get('/api/inference/status');response.raise_for_status()
        status=response.json()
        if (status.get('eye') or {}).get('active',False):
            raise RuntimeError('Webcam only; Eye is active')
    args.out.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        display=pool.submit(capture,args.out/'display',args.seconds,args.component)
        model=pool.submit(capture,args.out/'model',args.seconds,args.component,True)
        report={'display':display.result(),'model':model.result(),
                'limitation':__doc__, 'component':args.component}
    (args.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if any(report[key]['error'] or not report[key]['frames'] for key in ('display','model')):
        raise SystemExit(1)


if __name__=='__main__': main()
