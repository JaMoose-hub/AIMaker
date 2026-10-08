# Mobile chat vertical space — isolated browser QA

Date: 2026-10-06 (Asia/Taipei)

## Scope and environment

- Real `MobileWebApp` at `/phone` in `frontend/tools/wiring-chat-preview.mjs`, bound to loopback port 18810.
- Three synthetic wiring photos and the same unsent draft `保留我的未送出草稿` before and after the change.
- The fixture contains no production fallback, real camera, AI, or Pi route. No analysis was requested during this layout check.
- Chrome on Windows. Its existing 110% zoom was preserved; viewport override 429×929 produces 390×845 CSS px. Actual measured dimensions below are CSS px.

## Portrait comparison

| Element | Before | After | Change |
|---|---:|---:|---:|
| Visible message area | 488.06 | 659.87 | +171.81 (+35.2%) |
| Composer | 159.40 | 69.79 | -89.61 |
| Header | 69.59 | 60.59 | -9.00 |
| Bottom navigation | 66.60 | 54.60 | -12.00 |
| Textarea, one line | 88.81 | 44.00 | -44.81 |

Workspace details/language are collapsed by default, saving another 61.19 px. Before/after used the same viewport, conversation, photos, and draft. Document/body widths remained 390 px.

## Behavior and responsive checks

- Workspace details expand/collapse with meaningful accessible button labels and expanded state.
- Switching to English updates header, composer controls, navigation, and chat guidance; unsent draft is retained. Collapsing details also preserves the draft.
- Attachment, photo, and send buttons have accessible names. Header/composer/navigation controls have CSS 44 px minimum touch height; zoom-adjusted bounding measurements were 43.996 px.
- With no GPIO photo in shared view, bottom navigation shows only Chat and Stream. Existing chat attachment photos remain accessible in the conversation.
- Empty draft disables Send. A 12-line English draft grows the textarea to its 120 px cap with internal scrolling; restoring a one-line draft shrinks it to 44 px.
- 320×845, English: no horizontal overflow, including the longer header/status labels and multiline draft; composer controls stay within the viewport.
- 390×480 reduced-height window: message area 295.02 px; composer and navigation remain visible, no horizontal overflow.
- 845×390 landscape: message area 205.32 px; composer/navigation remain visible, centered app width 760 px, no horizontal overflow.
- Temporary viewport override and dedicated QA tabs/server were cleaned up after validation.

Reduced window height is only a layout approximation of a software keyboard; actual iPhone Safari keyboard/safe-area behavior was not exercised. No iPhone or hardware acceptance is claimed.

## Other validation reported by implementation owner

- 81 existing related mobile frontend tests passed.
- TypeScript and Vite build passed; existing large-chunk warning remains.
- Production HTTP 8100 and HTTPS `/mobile` returned 200 and referenced `index-ChtXKtvW.js`.
- Only frontend dist was updated. Backend was not restarted, and pairing was not invalidated.

## Evidence

- `before-portrait.jpg`, `after-portrait.jpg`
- `after-info-english.jpg`
- `after-320-multiline.jpg`
- `after-short.jpg`, `after-landscape.jpg`
- `before-metrics.json`, `after-metrics.json`, `size-metrics.json`
