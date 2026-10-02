# Compact workspace header — 2026-10-01

CSS-only spacing and size adjustment. Logo, Vibe Maker Studio, all three workflow
buttons, AI model, Pi connection, execution, controller, language, theme and save
status remain. No changes to React state, handlers, APIs or stored project data.
Logo display scales proportionally to 112 x 35; the original PNG is unchanged.

## Measured in the actual App, isolated production-build fixture

1651 x 871, Chinese/dark, same state and panel width before/after:

| Region | Before | After |
| --- | ---: | ---: |
| Entire header | 118px | 93px |
| Logo/navigation row | 66px | 53px |
| Settings row | 50.67px | 38.67px |
| Conversation | 486.67px | 511.67px |

25px (21.2%) less header height, all returned to conversation height. Header has
no fixed height, no clipped overflow and does not hide error/status feedback.

Additional browser checks:

- English/light at 1440 x 871: 93px header, no horizontal overflow.
- English/light at 1352 x 871: 117px header; status wraps, all controls retained.
- English/light at 390 x 871: no horizontal overflow, runtime selects 44px high,
  navigation targets >=44px, logo and subtitle visible.
- English/light at 1440 x 600: 93px header, all stages visible, no horizontal overflow.
- Model and execution popovers opened within the viewport below the compact
  header. No setting, hardware action or model request submitted from them.
- No browser warnings/errors. Fixture is separate from localhost:8100 and has
  no backend proxy or real hardware. Production tab/data were not changed.

`npm run test:theme` (22 tests), `npm run test:stages` (6 tests) and production
build passed. Existing Vite bundle-size advisory remains. Full frontend/backend
suites and physical hardware tests were not rerun for this CSS-only change.

Screenshots: [dark Chinese](dark-zh-header.png), [light English](light-en-header.png),
[mobile](light-en-mobile.png). All screenshots use isolated synthetic data.
