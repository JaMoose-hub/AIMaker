# AI glass orb refresh

Replaced the flat outlined collapse control with a 36px dimensional cyan/blue sphere inside the existing 46px button. Gloss, an internal light ribbon and a star core provide the resting identity; hover or keyboard focus crossfades to the directional arrow. The halo animates only opacity over 5.6 seconds. Reduced-motion disables it. The light theme retains a darker rim and shadow for contrast.

No event handlers, state, source selection, chat lifecycle or hardware behavior were changed.

Validation:

- 32 Node tests passed (`chat-presentation.test.mjs`, `assistant.test.mjs`), one execution each.
- `npm run build` passed; existing chunk-size warning remains.
- Isolated offline GPIO fixture on port 18807, 1413 × 871 browser: dark, light, hovered and collapsed screenshots inspected. No runtime errors or error overlay.
- Hover changes core opacity 1 → 0 and arrow opacity 0 → 1; actual hit area remains 46 × 46.
- Mouse collapse and keyboard Enter reopen retain exact video/chat/input DOM identity and the unsent draft.
- Reduced-motion: halo animation `none`, orb transition `0s`.
- Production port 8100 serves the rebuilt frontend entry. User's tab was not reloaded and backend was not restarted. Isolated browser and fixture were closed.

Screenshots: `backend/runs/diagnostics/photo-links-20261003/orb-glass-{dark,light,collapsed}.png`.

Browser checks used agent-browser and agent-browser-verify skills. These are UI/software checks only, not real-device or electrical validation.
