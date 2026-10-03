# Mobile prototype implementation verification — 2026-10-02

## Passing software checks

- Backend targeted regression: 195 passed across assistant, immutable photo geometry/reference/checks, mobile media/API/RTC, model owner locks, CUDA preprocessing/pose, YOLO profile, glasses and camera model/reset.
- Final assistant/mobile/no-webcam checks after reference binding and explicit `inherit_media:false` retry snapshots: 54 passed. Model-owner replacement/lifecycle follow-up: 5 passed. Main integration uses no webcam frames and fake YOLO/geometry/AI; it exercises actual main lifecycle, HTTP multipart normalization, capture storage, shared wire view and durable AssistantService media jobs.
- Mobile backend owner suite: 24 passed. Includes **actual localhost aiortc** synthetic 320×240 publisher → MediaRelay → viewer, separate incoming-video/sampling counters, bounded cleanup, plus **actual FFmpeg** synthetic video extraction.
- Desktop `npm test`: 558 passed including TypeScript/Vite build. Subsequent reference UI changes have focused tests and rebuilt output; exact final count/build is in [desktop QA](../../frontend/tools/qa-mobile/README.md).
- Expo: TypeScript, Expo dependency/prebuild/config checks and iOS/Android Hermes JS exports passed. Final test count and photo-format/reference changes are in [mobile README](../../mobile/README.md).
- PowerShell startup script parsed successfully. Git whitespace check passed.

## Existing environment-dependent failures

An additional backend core/camera/API/lifecycle run yielded **85 passed, 2 failed**. The failed assertions read the developer's ignored `backend/config.yaml` and expect an older rig/model configuration:

- `test_config_loads_yaml_relative_to_backend_dir`: expects `HD Pro Webcam C920`; the existing local setting is `MX Brio`.
- `test_default_config_enables_both_component_models`: expects `mrd-tf240-8p-cs-pose.onnx`; the existing local setting selects `mrd-tf240-8p-cs-pose-v3-lit-wired-last.onnx`.

No camera/model configuration was changed to satisfy these stale assumptions. Do not report this additional run as wholly passing or as physical camera validation.

## Evidence boundaries

Desktop screenshots use a synthetic 18788 fixture; its camera image, coordinates, frame rates and AI replies are simulated. The fixture was stopped. Local aiortc tests prove Python negotiation/relay can execute here, not native iPhone compatibility or 1080p30 Wi-Fi throughput.

Not performed: EAS dispatch/signing/iPhone installation, native New Architecture WebRTC build validation, real iPhone LAN stream/FPS/latency, camera module handoff, actual Pi/HC/TFT photo accuracy, live Codex image reasoning, physical webcam regression or Pi/electrical operations. Existing production server was not restarted. Startup and iPhone installation instructions are in [the guide](../mobile-prototype.md).
