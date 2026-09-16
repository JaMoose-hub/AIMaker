"""Bounded read-only capture of paired Webcam component model images."""
import base64
import json
import time
import argparse
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', required=True, choices=['hc-sr04', 'mrd-tf240-8p-cs'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    after = -1
    with httpx.Client(base_url='http://127.0.0.1:8100', timeout=5) as client:
        status = client.get('/api/inference/status'); status.raise_for_status()
        if (status.json().get('eye') or {}).get('active', False):
            raise RuntimeError('Eye active; Webcam capture only')
        start = time.monotonic()
        while time.monotonic()-start < 12:
            response = client.get('/api/tracking/component-source', params={
                'component_id': args.component, 'after': after})
            if response.status_code == 204:
                time.sleep(.03)
                continue
            response.raise_for_status()
            packet = response.json()
            after = packet['frame_id']
            assert packet['component_pose']['frame_id'] == after
            name = f'{after}.png'
            (args.out/name).write_bytes(base64.b64decode(packet.pop('image').split(',',1)[1]))
            packet['image_path'] = name
            rows.append(packet)
    (args.out/'sequence.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    from collections import Counter
    print({'frames':len(rows),'tracking':dict(Counter(r['component_pose']['tracking'] for r in rows)),
           'reasons':dict(Counter(r['component_pose']['pose_quality'].get('reason') for r in rows))})


if __name__ == '__main__':
    main()
