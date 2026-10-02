# Supplied Tinkro wordmark — 2026-10-01

- Reused `frontend/public/brand/tinkro-dark.png` byte-for-byte. SHA-256 matches
  the supplied `tinkro logo dark transparent (2).png`:
  `8f1e0d78ea6bd5f278ce34309c17906f7ffb7b906c351c2b80e0940b43f59345`.
- Full wordmark replaces the small symbol and typeset name. The Vibe Maker
  Studio subtitle remains visible, including narrow layouts.
- CSS displays the image at 128 x 40 with proportional cover/position to remove
  excess transparent canvas from the header. Source pixels are unchanged.
- Light mode keeps a dark backing for white logo lettering. No generated logo,
  filter/recolor, new library, business API or data migration was introduced.
- React presentation review: accessible heading/image name retained; explicit
  display dimensions reserve space; no new state, hooks, listeners or requests.

## Verification

- `npm run test:theme`: 20 passed, including exact source asset checksum,
  accessible wordmark, theme backing, stored preferences and theme isolation.
- `npm run test:stages`: 6 passed.
- `npm run build`: TypeScript and production Vite build passed. Existing bundle
  size advisory remains.
- Actual production App in the isolated `maker-stage-preview.mjs` fixture:
  dark/Chinese and light/Chinese at 1280 x 720; light/English at 390 x 844.
  Image loaded at native 2048 x 1024; desktop header row is 66px high. No
  horizontal overflow; mobile document width 375px within 390px viewport.
  Subtitle and three navigation buttons remain visible; no console warnings/errors.
- Read-only HTTP checks on localhost:8100 returned the current production
  JS/CSS and the 956028-byte original PNG with status 200 and image/png.
- User production tab/data were not reloaded or modified. No Pi, camera or cloud
  operation was started. Backend/hardware tests and the entire frontend suite
  were not rerun for this logo-only change.

Screenshots: [dark header](dark-header.png), [light header](light-header.png),
[mobile light English](mobile-light-en.png). These use isolated synthetic data.
