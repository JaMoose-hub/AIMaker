# Debug / saved-photo stream isolation

## Scope

User reported unstable live phone video after the failed-component-test **Ask AI for help** button, and requested inspection of related flows. Checked initial invitation, start/later, upload, capture completion, two-stage POC analysis, retry, stale results, and explicit debug stop. Existing UI and hardware execution behavior were preserved.

## Evidence and changes

- The initial invitation imports a consent message, not a model request. Injected slow invitation persistence did **not** block native frame receipt. This does not establish the cause of every reported real-device interruption.
- `MobileService.test_help_action` held the media receipt lock across debug creation, assistant/debug locks and disk persistence. Slow start and later actions reproduced receipt timeouts. Removed the broad media lock while retaining assistant/owner serialization and repeated workspace/source checks.
- `_analyze_capture` wrote its saved packet and bound the assistant photo reference synchronously on the native RTC event loop. Injected delays blocked that loop. Both now run in workers; the short media commit follows successful persistence. Chat binding rechecks current capture/context/generation after waiting for its lock, so delayed work cannot overwrite a newer selection.
- `/api/mobile/assets` spooled and cleaned up files synchronously inside an async endpoint. Converted the complete handler to a synchronous FastAPI worker endpoint, including bounded reading, ingestion, closing and cleanup. No parallel media pipeline or larger frame buffer was introduced.
- The existing phone-review test assumed one model call, predating the current POC inventory + pin-review pipeline. It now asserts both named receipt stages, checks native receipt during each deliberately delayed fake model call, and checks that explicit debug stop leaves the phone publisher active.

## Verification

- Final relevant coverage: **32 distinct passing cases** (11 new isolation/ownership/failure tests, 17 existing flow cases including the updated two-stage test, 4 previous media-isolation tests).
- **49 case executions** including intentional red tests and reruns, within the requested 50. One initial collection attempt from the repository root ran no tests; rerun from `backend` resolved its import path. Early test harness issues (desktop/phone action payload and exception type) were corrected before the successful red reproduction.
- Covered retry deduplication, simultaneous consent, context changes during creation, cancellation without recapture, delayed/out-of-order results, failed persistence, oversized-upload cleanup, upload authorization, POC model errors and switching away from pending analysis.
- Python compilation and scoped whitespace checks passed. Only existing Starlette/httpx test-client deprecation warning occurred in passing tests.
- Read-only live snapshot before deployment: phone active, generation 9, runtime revision 19, no live-source error; latest receipt age 15 ms. This is a baseline from the still-running old backend, **not** validation of deployed fixes.

## Deployment / limits

After explicit user confirmation, restarted the verified backend supervisor and its Python children; retained the HTTPS gateway. New supervisor PID 44172, backend PID 37908. Desktop root/config returned HTTP 200; phone HTTPS root returned 200 with certificate verification. Fresh backend stderr was empty. The saved debug conversation is paused with `backend_restarted`; no analysis or hardware work was replayed. Phone pairing/stream and Pi connection need reconnecting after restart.

No real AI calls, GPIO tests, electrical checks or physical camera actions were initiated. Automated tests use fake RTC/model/Pi and synthetic images, not long-duration real-network acceptance. No frontend changes or new UI were made in this turn.
