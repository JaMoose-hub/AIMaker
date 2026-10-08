# Photo and crop delivery visibility — 2026-10-06

## Live evidence (read-only)

Session `8817c9f504ba44fb83e62d702c835002`, review
`a34f9119d7d348999d86d7664ff0b319`, round 1, revision 12,
analysis revision 11, pipeline `poc-exit-pin-demo-2048-v3`.
All three selected photos are available; the completed receipt took 61,112 ms.

The Pi side B capture `be1db2c6901e48c7a2ef2310e50218ae` has a
4000 × 3000 original. Its saved normalized crop matches the user's screenshot.
Both cloud stages received the 2048 × 1536 overview and the 2048 × 1593 detail,
cropped from original pixels `[952, 659, 3255, 2450]`. Pi side A and the component
header reused their earlier observations and were not resent in this check.
The saved input key matches the current captures/crops and model policy.

The result requests a Pi angle that separates the overlapping header rows; it
does not indicate missing photos. No new cloud call or hardware job was made
during this verification. The recorded pin uncertainty remains uncertainty.

## Fix

- Show unsaved crop, saved input awaiting analysis and source-bound completed
  analysis separately. Retained old receipts cannot certify a changed crop.
- A compact receipt on desktop and phone lists actual overview/detail dimensions
  and explicitly identifies reused views. Historical messages cannot borrow it.
- Ordinary chat uses role-specific selected/available/crop state. Saving a crop
  preserves the photos; a complete set waiting for analysis is no longer labelled
  as missing photos. Text chat receives no new visual inspection automatically.
- Only current completed findings with the existing matching input key enter
  ordinary chat context. Generic media cannot bypass the explicit photo workflow.

## Verification

38 distinct automated cases passed after 39 executions, below the 50 limit:

- `test_wiring_chat_photo_state.py`: 3 passed.
- `test_wiring_photo_collection_gate.py`: 7 passed. One old assertion expected
  a single cloud request; updated it to verify both actual POC stages and all
  source IDs, hashes, sizes and supplied image hashes; reran only that case.
- `wiring_photo_status.test.mjs`: 7 passed.
- `wiring_chat.test.mjs`: 19 passed.
- `mobile_wiring_chat.test.mjs`: 2 targeted presentation cases passed.
- `npm run build`: passed; existing large-chunk advisory remains.
- Targeted `git diff --check`: passed.

Browser verification rendered the real saved review through the production
`WiringPhotoDelivery` component on a temporary loopback read-only page. Expanding
the receipt showed both dimensions and the two reused views. No capture or
analysis action is provided by that page. This is UI/receipt verification, not
a new model accuracy or physical wiring test.

The frontend build is available on the existing service. After the user explicitly
requested a restart, the supervised backend restarted at 14:17:24 on 2026-10-06
(worker PID 12556). The page returned HTTP 200 with `index-DhMCRKd6.js`, and
`/api/ai/status` reported logged in and idle. The old session is paused with
`backend_restarted` and its photo review is stale, as expected. Pi is disconnected
and must reconnect for hardware operations; no new hardware job or model call was
started during restart verification.
