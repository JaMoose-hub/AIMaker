# Mobile chat analysis button — isolated UI verification

Date: 2026-10-06 (Asia/Taipei)

## Scope

Used `frontend/tools/wiring-chat-preview.mjs`, bound to loopback port 18810, with the real `MobileWebApp` (`/phone`) and desktop `UnifiedAssistant` (`/`). The fixture owns all API routes and uses three synthetic SVG photos. It exposes no real model, camera, Pi, or production fallthrough route. No production service was restarted or modified by this verification.

## Results

- Prepared one synthetic review with Pi side A, Pi side B, and component header photos. Latest shared message was `wiring-message-7`, `analysis_request`, review revision 4 / round 1, conversation round 2 / epoch 0.
- Mobile chat displayed enabled **開始分析** directly beneath **照片齊了，可以開始分析。**
- Entered the unsent draft **保留我的未送出草稿**. Clicking the button sent exactly one `POST /api/mobile/wiring-review` with `action.op=analyse`, matching `review_id` and revision 4, plus the message/flow/request identifiers in `dialogue`.
- The fixture committed one synthetic analysis. Both real mobile and desktop chat components displayed the resulting `wiring-message-8`, `wire_review`, review revision 5. Both showed **還需要確認線路兩端**, and expanding details showed **Echo → Pin 18 無法確認**.
- The old analysis button no longer appeared after the result arrived; the mobile unsent draft remained unchanged.
- At 390 CSS px width, the document and body both measured 390 px; no horizontal overflow. Existing browser zoom was 110%, so viewport overrides 429×928 and 429×929 mapped to 390×843 and 390×845 CSS px respectively, bracketing the intended 390×844 test. Temporary viewport override was reset afterward.
- Captured browser error logs were empty on both pages. Fixture counters reported zero real model calls and zero real hardware calls.

## Evidence

- `phone-analysis-ready.jpg`: mobile button and unsent draft.
- `phone-analysis-result.jpg`: mobile shared analysis result and retained draft.
- `desktop-shared-analysis.jpg`: same result in desktop chat.

This verifies browser rendering and client transport against a closed synthetic API. It does not establish iPhone Safari behavior, production backend acceptance, real AI inference, real photos, or hardware/electrical correctness. Backend contract and unit tests are tracked separately by the implementation task.

## Implementation and service verification

- Root cause: the phone rendered capture actions only; backend mobile dialogue projection and action allowlists also excluded `analyse`.
- Phone now renders Start analysis / Retry analysis on the current shared message. The action carries the same message, flow, review revision and request identifiers as the shared workflow. Busy actions stay visible but disabled; obsolete messages cannot submit. Drafts and camera state are retained.
- The response immediately updates the shared conversation. Delayed responses cannot replace a newer result or a new conversation epoch.
- Frontend: 86 tests passed across `mobile_wiring_chat`, `mobile_web`, `mobile_chat_image`, and `mobile_wiring_review`; TypeScript and Vite build passed (existing large-chunk advisory).
- Backend: six new `test_mobile_wiring_analysis.py` cases passed. Agent's three-suite run: 30 passed, one existing clock-test failure (`test_wiring_analysis_chat.py` expects one fake bridge call, current pipeline makes two). Restoring this task's two backend allowlists in an isolated process reproduced the same failure; its expectation was not changed.
- Production had no active model job or wiring analysis before activation. Its most recent three-photo review was already paused/stale from the preceding backend restart; the archived photos were not deleted or promoted back into a current review.
- At 13:52 Asia/Taipei, the exact Tinkro supervisor/backend process tree was restarted. New backend PID 17088 listens on 8100; `/api/config`, `/`, `/mobile` returned HTTP 200. `/mobile` served new `index-0GylJugR.js`; HTTPS `/mobile` returned 200 with the existing root CA strictly verified. The HTTPS gateway was not restarted.
- Users must refresh both pages and pair again if necessary. The already-stale photo round needs a new photo-review workflow. No production analysis was triggered for QA and no iPhone real-device test was performed.
