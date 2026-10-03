"""Clean same-photo crops shared by uploaded and webcam photo analysis."""
from pathlib import Path
import math
import cv2
import numpy as np


def photo_inputs(packet, image_path, directory):
    image_path = Path(image_path)
    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    paths = [image_path]
    views = [dict(name="photo", frame_id=packet["frame_id"], image_sha256=packet["image_sha256"], size=packet["video_size"])]
    for message in [packet["detection"], *packet["components"]]:
        points = [(p["x"], p["y"]) for p in message.get("pins", []) if p.get("v") and
            all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k]) for k in ("x", "y"))]
        if frame is None or message.get("tracking") != "locked" or not points:
            continue
        h, w = frame.shape[:2]
        x0, y0 = max(0, int(min(p[0] for p in points)-96)), max(0, int(min(p[1] for p in points)-96))
        x1, y1 = min(w, math.ceil(max(p[0] for p in points)+97)), min(h, math.ceil(max(p[1] for p in points)+97))
        if min(x1-x0, y1-y0) < 16:
            continue
        name = message.get("component_id", "pi_header")
        path = Path(directory)/(name+".png")
        if cv2.imwrite(str(path), frame[y0:y1, x0:x1]):
            paths.append(path)
            views.append(dict(name=name, source_view="photo", crop=[x0,y0,x1,y1], frame_id=packet["frame_id"], adds_no_detail=True))
    return paths, views
