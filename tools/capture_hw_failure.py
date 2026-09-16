"""Capture bounded actual model-source failures, not newer display frames."""
import base64
import json
import sys
import time
from pathlib import Path
import httpx

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
after, count = -1, 0
started = time.monotonic()
with httpx.Client(timeout=5) as client:
    while time.monotonic()-started < 20 and count < 3:
        response = client.get('http://127.0.0.1:8100/api/tracking/component-source',
                              params={'after': after})
        if response.status_code == 204:
            time.sleep(.1)
            continue
        response.raise_for_status()
        packet = response.json()
        after = packet['frame_id']
        if packet['component_pose']['pose_quality']['reason'] != 'pin_orientation_unverified':
            continue
        count += 1
        (out / f'{count}.png').write_bytes(base64.b64decode(packet.pop('image').split(',')[1]))
        (out / f'{count}.json').write_text(json.dumps(packet, indent=2), encoding='utf-8')
print({'failures_saved': count})
