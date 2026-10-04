# Synchronous header disclosure

## Cause and fix

- The original mutual-exclusion check inspected settled state only. Native `details` expansion happened before the delayed `toggle` event updated the shared React owner, briefly showing phone and Settings together.
- The user's currently loaded entry was `/assets/index-DyXxtn8B.js`. Replaying that exact retained entry with a DOM-mutation monitor reproduced one overlap during phone -> Settings, although its final state contained only Settings.
- Pi and Settings now cancel native summary expansion and switch the shared owner directly in the click handler. Removed their `onToggle` state feedback.
- Settings keyboard dismissal now uses outside `focusin`, not `focusout` with a possibly null related target. Escape and pointer dismissal remain intact.

## Verification

- 34 related tests passed, including the real summary activation handlers, native `preventDefault`, and switching ownership without waiting for `toggle`.
- Production TypeScript/Vite build passed; the existing large-chunk warning remains.
- An isolated production-bundle preview monitored every panel DOM change. Old entry: phone -> Settings produced overlaps=1. New entry: all six directed switches, rapid cycles in photo mode and Enter/Space operation stayed at overlaps=0.
- New preview console reported no errors. Screenshots: `header-native-overlap-before.png` and `header-panel-synchronous.png`.
- The preview used synthetic photos and fake API responses, not camera, Pi, cloud or electrical tests. Temporary tabs closed and preview server stopped.
- Read and briefly operated header controls on the original user page before browser access was interrupted. Did not reload that page or restart the backend, preserving its in-memory photo workspace. Refresh is required for an already-open page to load the new frontend.
