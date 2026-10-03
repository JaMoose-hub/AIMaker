# Transparent light-mode wordmark — 2026-10-03

Supersedes the dark light-mode backing described in the 2026-10-01 README.

- Removed the black backing from the light-mode logo. A scoped SVG color filter maps neutral white lettering to #10131c while preserving alpha and the original red-free blue/teal accents. Dark mode and optical HUD remain unfiltered; the original PNG remains byte-for-byte unchanged.
- Preserved the accessible title, tagline, 112 × 35 compact image size and existing header layout. No React, state or hardware changes.
- 24 focused tests passed: `tinkro.test.mjs`, `theme.test.mjs`, `workspace_header.test.mjs`. Production build passed with its existing chunk-size advisory.
- Browser verification used the production bundle in the isolated GPIO fixture. Light and dark at 1651 × 871 plus light at 390 × 871 were visually inspected. The light logo has a transparent backing and dark letters; dark retains white letters. No horizontal overflow, app errors or error overlay. Theme switching preserved the image DOM node, draft and project.
- Production HTTP served the new filter with status 200 and image/svg+xml. Legacy offline preview routes/asset allowlists also include this static filter, without opening network/API access.
- Screenshots: `light-transparent-header.png`, `dark-preserved-header.png`, `mobile-transparent-header.png`.

No live camera, phone, Pi, deployment or cloud model test. Owned browser/fixture closed after verification; user tab untouched.
