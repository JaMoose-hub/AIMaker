# Workspace publication — 2026-10-08

## Included work

The user requested publication of the current local version on
`feature/unified-assistant-demo`. Include the existing frontend layouts, material
illustrations, wiring guide and chat changes; mobile resolution/orientation and
stream ownership/isolation changes; compact history polling; Pi management
connection recovery; and the shared POC wiring-photo pipeline, tests and QA
documentation.

Local configuration, credentials, pairing/session records, original photographs,
generated QA imagery, build products, `frontend/tsconfig.tsbuildinfo` and the
empty root `innerWidth` artifact are excluded from this publication.

## Verification

- Production TypeScript/Vite build passed. The existing large-chunk warning remains.
- 21 frontend cases passed across test action icons, material illustrations,
  guide connection paths and component/stream isolation.
- 27 backend cases passed across publisher ownership, debug/stream isolation,
  the fast photo pipeline and source-bound row-only observations.
- These 48 cases are focused software regressions; the full test suite was not
  repeated. No real camera, cloud model, Pi job or electrical test was initiated.
- `npm run check:i18n` still reports two existing issues in
  `MobileLanguageSwitch`: the literal `aria-label="語言 / Language"` and JSX
  `繁中`. Both are present in the prior committed version. No product behavior
  was changed to suppress them.
- The backend tests retain the existing Starlette/httpx deprecation warning.
- Staged whitespace and repository publication checks passed after removing
  trailing blank lines in two test files. All five published model exports match
  their manifest; no ignored/private paths or oversized files are included.
- Gitleaks scanned the staged changes with redacted reporting and found no leaks.

This publication check does not establish long-duration streaming stability or
a 95% physical pin, wire or fault-recognition accuracy rate. The included QA
records preserve the earlier real-photo results and their remaining limits.
