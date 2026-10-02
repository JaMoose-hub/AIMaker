# Blueprint materials: USD estimates and partner opportunities

Verified 2026-10-01. Frontend presentation only.

## Behavior

- `材料與合作` / `Parts & partners` replaces the demo shopping tab label.
- Electronic and structural material cards show quantity and an estimated USD subtotal.
- Prices remain TWD in the original BOM and structural catalog; no persisted data, API, or project schema changed.
- Conversion: `unit price in TWD × quantity ÷ 31.842`, rounded only for the displayed subtotal to two decimals. Missing/invalid estimates display `待估價` / `Not estimated`.
- The pinned reference is **2026-10-01, NT$31.842 per US$1**, from the [Central Bank of Taiwan closing-rate table](https://www.cbc.gov.tw/en/lp-700-2.html). This is not a live rate or a supplier's US retail quote. The rate, date, source, shipping/tax disclaimer and quantity treatment are available under `估算方式` / `How estimates work`.
- `合作招商中` / `Partner opportunities` opens a native modal with the selected material and subtotal. It describes component supply, project kits and education partnerships, and explicitly states that sellers, stock and checkout are not connected.
- No contact address, supplier, inventory, checkout or outbound contact form is invented. A real contact channel can be connected separately when provided.
- All new UI copy is bilingual. Existing project-authored titles, descriptions and history are not rewritten or sent for translation.

## Automated checks

- `node --test tools/material_pricing.test.mjs`: 5 passing tests.
- `npm test`: 490 passing tests, zero failures; i18n validation and production build passed. The existing Vite bundle-size advisory remains.
- Coverage: pinned reference/source, unit and multi-quantity conversion, rounding after multiplication, invalid values, bilingual SSR output, electronics/structural estimates, unchanged frozen source data and accessible dialog triggers.

## Browser checks

Used the actual React components in the existing isolated `tinkro-preview.mjs` fixture, served on loopback port 18776. The fixture blocks fetch/WebSocket business requests and mocks hardware hooks. Synthetic prices and project descriptions are fixture data, not supplier offers or real hardware evidence.

- 1651×871: Traditional Chinese/dark and English/light material list and dialog.
- 390×844: English/light dialog fits without horizontal overflow; close target is 44×44 px.
- 1651×500: dialog stays within the viewport and scrolls; the return button remains reachable.
- Escape closes the modal and returns focus to the originating material button. The close and return buttons work; keyboard focus has a visible 2 px outline.
- A structural material with quantity 2 shows US$3.77 consistently in its list and dialog.
- Selected the HC-SR04+ GND build step, returned to materials, opened/closed the dialog, and compared DOM state: the selected step, full circuit markup and split ratio remained unchanged.
- No warning/error console entries during the checks.
- Did not reload or change the user's live 8100 tab, deploy or stop Pi, capture camera images, run GPIO tests, contact a supplier or make a paid AI request.

Screenshots:

- [Dark Chinese materials](materials-dark-zh.png)
- [Dark Chinese partner dialog](dialog-dark-zh.png)
- [Light English materials](materials-light-en.png)
- [Light English partner dialog](dialog-light-en.png)
- [Mobile English partner dialog](dialog-mobile-en.png)

The actual live app serves the rebuilt frontend assets; the isolated browser checks do not constitute a live hardware or procurement test.
