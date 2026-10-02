# Bundled Demo image

## Current: three wheels and two motors (v2)

`distance-monitor-three-wheel-motors-v2.png` replaces v1 in the Demo UI.
It was made with the built-in imagegen tool on 2026-10-01, editing the existing
three-wheel image `runs/project-images/5d8f91e23b1e40c889b2350910e69b71.png`.
The old image had three wheels but no visible motors. The edit adds two visible
yellow geared motors below the lower acrylic plate; all three rubber wheels
remain visible. The screen shows DEMO and a car/warning illustration.

- Size: 1536 × 1024 pixels.
- SHA-256: `4ced7d7fc35ed955d942f531e0d3286640e0f306c07b546c66724848e3cdb0fd`.
- Generated source: `C:/Users/james/.codex/generated_images/01a07981-d3f6-7572-a170-6998ad1aa148/exec-4ab5c26a-4c36-4c63-8b86-b66163a4ab03.png`.
- Exact prompt: [demo-image-motors-prompt.md](../../../docs/qa/demo-image/motors-prompt.md).
- Motors are unconnected appearance placeholders, not proof of a working motor system.
- Only the Demo image and its visible concept-only explanation change; motor BOM,
  wiring, tests, deployment and AI reference-image metadata are not added.
- Loading Demo uses the saved file; it does not generate or edit an image again.

### Retention boundary

This is a **bundled application asset**, not a user/project image. New project,
discard preview, clear conversation and clearing saved browser project data must
never delete, overwrite or replace it. These actions may remove the current Demo
from view; Load demo must still display this same v2 image afterwards.

Keep the canonical file in `frontend/public/demo`; production builds copy it to
`frontend/dist/demo`. Do not rely on an image-generation output directory, a
temporary file, browser storage or `runs/project-images` for the Demo asset.
Do not put this static URL into `ProjectDesign.image` or use it as an AI edit
target. It is only rendered for explicit Demo data; new/AI projects remain
independent. No filesystem read-only flags or OS permissions are necessary.

## Previous: stationary monitor (v1, retained)

`distance-monitor-v1.png` is an unchanged copy of the existing project image
`runs/project-images/a3e88610a0114acc95ee43901fe5e592.png` (2026-09-30).

- Size: 1312 × 1199 pixels.
- SHA-256: `04e08a59210e65a04afcde8b4884f632fe65b87875aedbb0a723ed7b69c12fb5`.
- Depicts the built-in full kit: Pi, ultrasonic distance sensor and TFT display.
- Historical AI-created illustration; loading Demo does not generate a new image.
- Appearance reference only, not exact hardware, wiring, dimensions or working-device evidence.

Only `source: "demo"` with both supported modules and no generated/required/error
image uses this fallback. It is not stored as a generated image artifact, sent to
AI as an edit target, or used to unblock missing AI images. Blueprint and runtime
still use their existing catalog data. Original source files are not changed.
