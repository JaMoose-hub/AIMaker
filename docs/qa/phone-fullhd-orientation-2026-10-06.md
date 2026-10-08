# Phone Full-HD and orientation policy — 2026-10-06

## Requested story

Open the phone camera at no less than 1080p, turn portrait to landscape, and
retain the same camera track / RTC peer while both phone preview and desktop
receive the new native geometry.

## Changes

The following records the initial iteration. The portrait-startup correction
below supersedes its screen-axis admission and directional-readiness rules.

- Camera acquisition requires 1920 × 1080 (landscape) or 1080 × 1920 (portrait)
  minimum dimensions. Legacy 720p options are normalized to 1080p. No automatic
  720p acquisition fallback and no upscaling to manufacture Full-HD pixels.
- Native decoded dimensions are verified before publishing. Unsupported cameras
  fail explicitly rather than starting an undersized publication.
- Sender requests `maintain-resolution`, initially with scale 1. The app's
  congestion policy may reduce larger inputs but respects both the 1080-pixel
  short edge and 1920-pixel long edge. Native browser behavior is still measured,
  not assumed: the phone warns when actual uploaded/received frames are smaller.
- Orientation reapplies width/height/aspect constraints on the existing native
  track. Constraints are serialized, latest orientation wins, Stop cancels
  continuations, and a hung operation cannot spawn overlapping adjustments.
- Capture readiness is withheld while settling, undersized, or directionally
  inconsistent. The stream and visible preview are retained on adjustment errors.
- Minimum resolution UI is fixed to 1080p; 30 FPS is explicitly a target. Smart
  adjustment no longer recommends a 720p restart. No permanent analysis toolbar,
  hardware wiring changes, or secondary capture pipeline was added.

## Validation

43 selected software tests passed:

- 26 browser-publisher / native-orientation / lifecycle cases.
- 9 stream-quality-policy cases, including the 4:3 long-edge floor.
- 5 mobile UI cases, including truthful sub-1080 and orientation warnings.
- 2 smart-adjustment cases.
- 1 hung-orientation serialization case.

One initial smart-adjustment test-file load failed because its existing mocked
module loader omitted `mobileStreamPolicy`. Fixed the fixture; the two selected
cases then passed. Total test executions including that loader failure: 44.
TypeScript `--noEmit`, Vite production build, and targeted `git diff --check`
passed. Vite retains the existing >500 kB bundle warning.

Served `/mobile` returns the new `/assets/index-BSftbc52.js`; production phone
chunk is `MobileWebApp-RC8H3KBc.js`. No backend restart performed.

## Live boundary / not yet verified

At the final local status check, `/api/camera/live-source` was `kind=webcam`,
`ready=false`, no phone session selected. Desktop UI likewise showed Webcam and
waiting for an image. The user was asked to reload the phone, start streaming,
and rotate it for live receive-size verification. No real-phone 1080p/orientation
acceptance, long-duration network reliability, or Pi/electrical test is claimed.

## API references

- [MDN applyConstraints](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/applyConstraints):
  applies a new constraint set; mandatory constraints can fail.
- [W3C WebRTC](https://www.w3.org/TR/webrtc/): sender degradation and scaling
  controls are distinct from actual measured outbound dimensions.

## Portrait-startup correction

- Screen orientation is no longer a camera-start prerequisite. Initial acquisition
  requests native Full HD independently of the handset orientation, with symmetric
  1080-pixel minimum edges and preferred (not mandatory) 1920 x 1080 geometry.
- Before publication, decoded pixels must still have a short edge >=1080 and a
  long edge >=1920. No 720p fallback or artificial upscaling was introduced.
- Screen/native-axis disagreement alone no longer rejects startup or capture.
  Orientation updates retain the native camera track and RTC peer. Failed optional
  orientation controls warn but allow stable Full-HD capture after settling.
- Regression testing exposed synchronous constraint-failure callbacks releasing
  capture readiness before the settling guard existed. The guard now precedes the
  adjustment request.

Validation: 39 distinct software cases have successful final results across browser
publication/orientation, stream policy, and mobile UI. There were 43 executions:
26/27 passed initially, then four focused cases passed after the settling fix,
followed by nine policy and three UI cases. TypeScript, production build, and
targeted diff checks passed. The existing Vite large-chunk warning remains.

Served `/mobile` references `index-CxHMGJmL.js`; the production phone chunk is
`MobileWebApp-DddDq27w.js`. No backend restart or live-stream interruption was
performed. The existing phone stream was active at 1920 x 1080 and 30 FPS at the
status check; this does not validate a newly reloaded upright startup. Real-phone
upright startup and rotation still require confirmation after refreshing the phone.
