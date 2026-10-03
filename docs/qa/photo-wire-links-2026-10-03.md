# Frozen-photo wire endpoints — 2026-10-03

## Report and cause

The 15:55 phone capture `64831c18cac54295aa6db6b525b9431b` contained Pi 5,
HC-SR04 and MRD-TFT240. Both component models supplied candidate regions, but
their independent photo geometry failed. The renderer correctly withheld a
wire with a missing endpoint, without explaining why in the compact view.

- HC: native-reference matching did not have enough unique physical support.
- TFT: four mounting holes were found, but low-contrast/slightly sloped LCD
  rails did not satisfy the axis-aligned/closed-contour orientation checks.

## Changes

- A lazy, cached, bounded bank of raw/CLAHE affine views of the **existing** HC
  reference; canonical coordinates and physical-support deduplication remain
  mandatory. No reference images, profiles, trained models or SIFT acceptance
  thresholds were changed. No temporal pose is reused.
- Photo-only TFT fallback measures four sloped LCD edges after local contrast
  enhancement. It still requires four observed holes, 70% support on each LCD
  edge, corner joins and unambiguous asymmetric panel inset. Missing/covered
  or symmetric geometry fails closed. Live tracking was not changed.
- Compact photo view explains which endpoint is missing. “Current endpoints”
  is disabled unless both endpoints are available; object inspection remains.

## Verification

- 31 backend tests passed: photo geometry, reference deduplication, and new LCD
  edge cases (including missing edges, clipped mounts and ambiguous direction).
- 35 frontend cases passed; one existing assertion was updated to the intended
  two-endpoint focus contract and rerun. 66 unique cases, 67 executions.
- `npm run build` passed. Existing large-bundle advisory remains.
- Three saved-photo geometry replays, zero new model forwards. The reported
  photo now locates all three objects; HC has 20 unique inliers, four quadrants,
  0.313 reference coverage and 0.730 px median error. TFT has four holes and
  0.924 minimum LCD-edge support. Earlier uncertain Pi/J8 results remain
  uncertain; previously located components did not regress.
- Isolated browser replay with agent-browser / agent-browser-verify: ECHO to
  GPIO18 has one dashed line; switching to TFT selects TFT's GND endpoint.
  Original unlocated packet shows a brief warning, no line and disabled
  two-endpoint focus. No browser errors. Both owned fixture servers and browser
  sessions were closed; the user's browser was not reloaded or modified.

Evidence is in `backend/runs/diagnostics/photo-links-20261003/`: original image
and packet, `regression-summary.json`, `ui-echo.png`, `ui-tft.png`, and
`ui-unlocated.png`. Captured image hashes were checked before replay/rendering.
Fixture source labels are synthetic; the actual input is the saved phone photo.

## Applied and limitations

At the user's explicit approval, restarted only the verified backend process;
the existing supervisor preserved its launch environment. Port 8100 returned
healthy with 1920 x 1080 configuration and realtime tracking enabled. No Pi
deployment/test was running locally; Pi was disconnected. The phone must be
reconnected and a new photo captured after refreshing the UI. Previous frozen
photos are immutable and are not silently rewritten.

This verifies same-photo coordinate recovery and intended-wire UI, not new
phone-stream capture accuracy, electrical continuity, voltage, or component
function. No hardware test, training, cloud analysis or manual wiring records
were performed/changed.
