# Inner / outer Pi header capture — 2026-10-06

## Delivered flow

- New checks collect Pi inner row (toward board centre), Pi outer row (toward
  board edge), then the module header. Desktop and phone use the same labels.
- Current Pi capture questions show a two-row framing illustration immediately.
  Users angle the camera from the requested side to expose insertion bases,
  keeping wire colours and a board corner in view. Optional tips stay collapsed.
- Existing crop, overview/detail analysis, photo receipts, shared conversation,
  manual decisions and hardware operations retain their existing controls.
- `capture_plan=pi_rows_v1` is frozen on new reviews and dialogue messages;
  saved photos carry `target_row`. Old side photos keep their legacy meaning.
- Both existing model stages receive source-bound `requested_row`. It is an
  intended capture target, never proof of observed row identity or a pin number.
- Pipeline `poc-exit-pin-demo-2048-v4-rows` and cache keys include the new plan
  and targets. A changed row target cannot reuse a legacy analysis receipt.
- Retakes use the expected pin's row derived from the existing Profile geometry.
  They do not select the opposite row just because some other connectors exist.
  Missing design geometry leaves both rows unresolved instead of guessing.
- Ordinary text chat receives selected photo targets, with the same distinction
  between an intended capture target and a visual observation.

## Verification

47 distinct automated cases passed in 48 executions. One initial UI assertion
incorrectly disallowed optional tips entirely; corrected it to require the row
illustration outside/before those tips, and reran only that case.

- `wiring_chat.test.mjs`: 22 cases.
- `wiring_photo_status.test.mjs`: 8 cases.
- `mobile_wiring_chat.test.mjs`: 2 focused presentation cases.
- `wiring_review.test.mjs`: 2 focused legacy/manual-authority cases.
- `test_wiring_row_capture.py`: 8 cases, including both stages, source binding,
  phone import, legacy history, cache identity, row-specific retakes and no
  automatic human confirmation.
- `test_wiring_chat_flow.py`: 4 focused shared capture/crop/phone/restart cases.
- `test_wiring_chat_photo_state.py`: 1 focused saved-photo/chat-context case.
- `npm run build` passed; existing bundle-size advisory remains.
- `git diff --check` passed; line-ending notices only.

Two browser flow checks used the closed loopback preview on port 18813:

1. Desktop: explicitly captured inner, outer and module views in order; the
   analysis button appeared only after all three. Draft text remained intact.
2. Phone at 390 x 844: shared outer-row question, immediately visible framing
   illustration and existing camera/album controls. Content width and viewport
   both measured 390 px.

The preview sent exactly three capture actions and no analysis action. Its
photos are synthetic; no real camera, cloud inference or hardware test ran.
This verifies UI/state/source handling, not a measured gain in pin-recognition
accuracy. That requires new real photographs of the requested rows.

## Runtime

Production frontend built as `index-DmMCoCS6.js`. The existing idle backend
restarted through its supervisor at 14:40:31 (new worker PID 45044). The page
returned HTTP 200 with that asset; AI status reported logged in and idle. The
prior active photo check is `backend_restarted` / `stale` and must be recaptured
under the new instructions. No live capture, cloud request or hardware job was
started to verify the restart.
