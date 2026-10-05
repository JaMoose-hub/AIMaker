# Wiring guide entry — 2026-10-05

## Change

- Page restoration opens the first project component at preparation/index 0.
- Saved inspection/source/return cursors are discarded; confirmations, guide run, design, draft code and conversation remain intact.
- Completed old confirmations no longer convert preparation into the function-test screen.
- Preparation does not offer a new component-test launch, but ongoing test/stop controls remain reachable.

## Evidence

- Before the change, the two new regression checks failed: completed records skipped preparation and the last selected component was restored.
- After the change, 159 related frontend tests passed, including guide restoration/navigation, historical test keys, live/foreign/disconnected tests, restart, Reset, edit, review and mobile test-help/review.
- TypeScript/Vite production build and i18n parity (761 keys) passed. Existing large-chunk warning remains.
- An isolated full-App page was seeded with all 11 confirmations, the second module selected and an old debug inspection. On open it displayed HC-SR04+ preparation. Start displayed GND → Pin 6 (1/4); Next visited TRIG, ECHO, VCC and only then function testing. Reload from a later wire returned to preparation.
- A separate isolated ongoing-test page retained Stop and offered no new HC-SR04+ test launch. Browser error logs were empty.
- The production localhost root returned HTTP 200 with the rebuilt `/assets/index-zBADzNG6.js` entry. No backend restart is necessary; the user must refresh the page.

Screenshots: [restored preparation](screenshots/wiring-guide-reopen-prepare-20261005.png), [first wire](screenshots/wiring-guide-first-wire-20261005.png).

Scope: software/isolated UI verification only. No real camera capture, Pi/GPIO function test, electrical acceptance, backend restart, workflow Reset or user-data deletion was performed. The isolated server and temporary tabs were closed.
