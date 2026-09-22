# Runtime models

Only the published Raspberry Pi 5, HC-SR04 and MRD-TF240 runtime models are included.
These are ordinary Git files, not Git LFS pointers. Together they occupy
approximately 54.3 MiB; each export is under 12 MiB.

| Component | Export | Purpose | Input size |
| --- | --- | --- | --- |
| Raspberry Pi 5 | `board-pose-pi5-guided-20260922.onnx` | Guided-data trial; opt-in | 960 |
| Raspberry Pi 5 | `board-pose-pi5-handheld-v2.onnx` | Main handheld board pose | 960 |
| Raspberry Pi 5 | `board-pose-pi5.onnx` | Reference-recovery detector | 960 |
| HC-SR04 | `hc-sr04-corner-pose-v3-robust.onnx` | Component corner pose | 768 |
| MRD-TF240 | `mrd-tf240-8p-cs-pose.onnx` | Component corner pose | 1280 |

Exact file sizes and SHA-256 checksums are in [manifest.json](manifest.json).
The credential-free [configuration example](../backend/config.example.yaml)
uses these exports. OpenCV CPU, ONNX Runtime CUDA and DirectML inference paths
remain available; choose a backend supported by the installed dependencies.

The runtime exports predict four semantic board corners. Geometry and pin
ordering come from the matching files under `profiles/`, not from model weights
alone. Keep those profiles and their required reference images when deploying.

Training checkpoints (`.pt`), datasets, experimental exports, model backups,
HW-123, photoresistor, segmentation and separate Eye model exports are not
included. Training tools and historical documentation may reference these local
assets; those workflows require separately prepared files. They are not required
for the bundled three-component webcam configuration.

## Guided Pi 5 trial (2026-09-22)

The new four-corner export is bundled for testing, not an unconditional accuracy
promotion. The public configuration example retains `handheld-v2` as its default.
To try the new model, change both paths in your local `backend/config.yaml`:

```yaml
yolo_pose:
  model_path: ../models/board-pose-pi5-guided-20260922.onnx
  board_model_paths:
    raspberry-pi-5: ../models/board-pose-pi5-guided-20260922.onnx
```

Keep all other settings and board mappings, then restart the backend. To roll
back, restore both paths to `../models/board-pose-pi5-handheld-v2.onnx`. The Pi
reference-recovery model and the HC-SR04/TFT models are unchanged.

The trial used 179 training images (104 existing + 75 guided) and the same 35
legacy validation images. Box mAP50-95 changed from 0.3451 to 0.6192; pose
mAP50-95 changed from 0.9732 to 0.9610. These PyTorch checkpoint metrics are not
an independent new-scene test, ONNX runtime benchmark or GPIO accuracy result.
The guided capture group was training-only; raw images/checkpoints stay local.

GPIO still comes from profile geometry, not 40 separately detected contacts.
The accompanying J8 refinement rectifies the projected header and checks its
long neutral-dark body, rejecting short attached chips, partial/ambiguous
housing evidence and invalid geometry. It preserves pin numbering and
perspective; rejected corrections leave the original projection unchanged.
Housing alignment and a tracking lock do not verify physical contacts or wiring.
