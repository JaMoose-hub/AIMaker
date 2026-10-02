# Concept-only motors — 2026-10-01

## Scope

Motors can be requested as appearance-only parts in the 01 concept image. They are held in `concept_only_parts`, not the catalog or passive structural BOM. Existing projects without that optional field remain valid. No motor drivers, GPIO, testing, runtime imports, device requirements or powered-motion behavior were added.

Old generated images are not regenerated automatically. A user must explicitly request a new design/revision for a motor image. No paid model/image generation or physical hardware action was performed during this validation.

## Automated checks

- Full frontend `npm test`: 497 tests passed, zero failures; production build passed (existing large-bundle warning).
- Full backend `python -m pytest -q`: 2004 passed, 2 skipped, 4 failed.
- Confirmed the same four failures with the pre-change HEAD versions of `designs.py`, `design_prompt.py` and `project_images.py` loaded in an isolated Python process. The checkout was not reverted.
- Existing failures: `test_config_loads_yaml_relative_to_backend_dir` expects C920 instead of MX Brio; `test_default_config_enables_both_component_models` expects the older TFT model; `test_component_reference_refresh_requires_material_hand_and_three_frames[hw-123]` targets the retired module; `test_prompt_disambiguates_imu_from_pir_without_adding_a_module` expects the retired IMU image instruction.
- New tests cover schema boundaries, legacy defaults, confirm/restore, fixed/free prompt context, mock image job persistence, unchanged BOM/wiring/code/requirements/debug identity, and bilingual concept-only notices.

## Browser verification

Used the loopback-only fixture at `http://127.0.0.1:18770/?conceptMotors=1`, then `&locale=en`, at the existing 1651×871 viewport. The fixture denies cloud/Pi actions and uses `connect-src 'none'`; it does not access production storage. Its schematic picture is labelled as a layout fixture, not a generated design.

- Chinese and English concept views show Motor × 2 with the image-only scope notice.
- Blueprint, stage 02 and stage 03 show no motor entries in either language.
- Existing two-module wiring remains 11 connections; stage 03 retains its original program.
- No browser console errors across either locale.
- Screenshots: `concept-zh.png`, `concept-en.png`, `blueprint-zh.png`, `blueprint-en.png`, `wiring-zh.png`, `wiring-en.png`, `deploy-zh.png`, `deploy-en.png`.

React Best Practices guided the use of derived render-only UI, without new effects, requests or hardware state. Agent Browser / Agent Browser Verify guided the visual checks; the environment's required CUA browser interface was used instead of a separate browser CLI.

## Running service

Restart preflight found AI idle and logged in, no local execution jobs, no component test or trial, and a stale paused debug session from an earlier restart. Pi was disconnected with unknown remote program state; no claim is made about remote hardware being stopped.

The environment policy rejected the backend stop/restart command before execution. The old listener remained PID 58376 on port 8100. The built frontend is available, but the new backend prompt/schema rules need a permitted service restart. No alternative termination mechanism was attempted.
