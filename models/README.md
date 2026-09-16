# Runtime models

Only the active Raspberry Pi 5, HC-SR04 and MRD-TF240 models are included.
These are ordinary Git files, not Git LFS pointers. Together they occupy
approximately 43.5 MiB; each export is under 12 MiB.

| Component | Export | Purpose | Input size |
| --- | --- | --- | --- |
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
