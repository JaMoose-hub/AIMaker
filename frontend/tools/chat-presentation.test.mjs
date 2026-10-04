import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
test('design and debug chat distinguish messages from notices with consistent bubbles',()=>{
  const maker=read('../src/maker.css'),theme=read('../src/tinkro.css');
  assert.match(maker,/\.maker-assistant \.maker-conversation\s*\{[^}]*display: flex; flex-direction: column/);
  assert.match(maker,/\.maker-message\.user\s*\{[^}]*align-self: flex-end/);
  assert.match(theme,/:is\(\.maker-message, \.ai-debug-message\)\s*\{[^}]*border: 1px solid[^}]*border-radius: var\(--radius-card\)/);
  assert.match(theme,/:is\(\.maker-message\.user, \.ai-debug-message\.is-user\)\s*\{[^}]*border-radius: var\(--radius-card\)/);
  assert.doesNotMatch(theme,/:is\(\.maker-message, \.ai-debug-message\)\s*\{[^}]*border-left:/);
});

test('the actual message box contains only text and send, with optional tools kept outside',()=>{
  const panel=read('../src/components/AiDebugPanel.tsx');
  const row=panel.slice(panel.indexOf('<div className="ai-debug-compose-row">'),panel.indexOf('<div className="ai-debug-composer-toolbar">'));
  assert.match(row,/<textarea[^>]*id="ai-debug-message"/);
  assert.match(row,/className="ai-debug-composer-send"/);
  assert.doesNotMatch(row,/captureStep\(|selectKind\(|<select/);
  assert.match(panel,/<label htmlFor="ai-debug-message">/);
  assert.match(panel,/onCompositionStart=[\s\S]*onCompositionEnd=/);
  const theme=read('../src/tinkro.css');
  assert.match(theme,/:is\(\.maker-compose-row, \.ai-debug-compose-row\):focus-within/);
  assert.match(read('../src/debug.css'),/\.ai-debug-composer textarea\s*\{[^}]*min-height:64px; max-height:128px/);
});

test('stacked chat keeps a readable history when controls and drafts wrap',()=>{
  const css=read('../src/guideAi.css');
  assert.match(css,/@media \(max-width: 960px\), \(max-height: 600px\)\s*\{[^]*?\.wiring-workspace:has\(\.wiring-workspace-tabs > button:last-child\[aria-selected="true"\]\)\s*\{ height: auto; min-height:/);
  assert.match(css,/\.wiring-workspace \.ai-debug-chat\s*\{ flex: 0 0 clamp\(180px, 32dvh, 320px\); min-height: 180px/);
});

test('unified chat uses distinct theme-aware user/AI bubbles above legacy specificity',()=>{
  const css=read('../src/assistant.css');
  for(const role of ['user','ai']) {
    assert.match(css,new RegExp(`--chat-${role}-bg: #[0-9a-f]{6}`));
    const light=css.match(/:root\[data-theme="light"\] \.unified-assistant\s*\{([^}]+)\}/)?.[1];
    assert.ok(light.includes(`--chat-${role}-bg:`));
  }
  assert.match(css,/\.app\.tinkro-theme:not\(\.display-mode-active\) \.unified-message-list \.ai-debug-message\.is-user\s*\{[^}]*background: var\(--chat-user-bg\)/);
  assert.match(css,/\.app\.tinkro-theme:not\(\.display-mode-active\) \.unified-message-list \.ai-debug-message\.is-assistant\s*\{[^}]*background: var\(--chat-ai-bg\)/);
  assert.match(css,/\.is-user > header > strong\s*\{ color: var\(--chat-user-ink\)/);
  assert.match(css,/\.is-assistant > header > strong\s*\{ color: var\(--chat-ai-ink\)/);
});

test('unified composer restores a non-intercepting glow with focus and reduced-motion support',()=>{
  const css=read('../src/assistant.css');
  assert.match(css,/\.assistant-input\s*\{[^}]*isolation: isolate[^}]*padding-box[^}]*border-box/);
  for(const layer of ['before','after']) {
    assert.match(css,new RegExp(`\\.assistant-input::${layer}\\s*\\{[^}]*pointer-events: none`));
  }
  assert.match(css,/\.assistant-input::before\s*\{[^}]*filter: blur\(18px\); opacity: var\(--prompt-glow\)/);
  assert.match(css,/\.assistant-input:focus-within\s*\{ outline: 2px solid/);
  assert.match(css,/\.app\.tinkro-theme:not\(\.display-mode-active\) \.assistant-input textarea:focus-visible\s*\{ outline: none;/);
  assert.match(css,/\.assistant-input:focus-within::before\s*\{ opacity: calc\(var\(--prompt-glow\) \+ \.14\)/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)\s*\{ \.assistant-input::before \{ transition: none;/);
});

test('unified draft has a slim theme-aware scrollbar without arrows and remains scrollable',()=>{
  const css=read('../src/assistant.css');
  assert.match(css,/\.assistant-input textarea\s*\{[^}]*--prompt-scroll-thumb: color-mix\(in srgb, var\(--ink-secondary\)/);
  assert.match(css,/\.assistant-input textarea\s*\{[^}]*resize: vertical; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain/);
  assert.match(css,/scrollbar-width: thin; scrollbar-color: var\(--prompt-scroll-thumb\) transparent/);
  assert.match(css,/textarea::-webkit-scrollbar\s*\{ width: 5px; height: 5px;/);
  assert.match(css,/textarea::-webkit-scrollbar-thumb\s*\{[^}]*border-radius: 999px/);
  assert.match(css,/textarea::-webkit-scrollbar-button\s*\{ display: none; width: 0; height: 0;/);
  assert.match(css,/@supports selector\(::-webkit-scrollbar\)\s*\{\s*\.assistant-input textarea\s*\{ scrollbar-width: auto; scrollbar-color: auto;/);
});

test('AI orb has low-gloss midnight glass and an interaction-only directional affordance',()=>{
  const css=read('../src/assistant.css');
  const orb=css.slice(css.indexOf('.assistant-orb {'),css.indexOf('.assistant-resizer {'));
  assert.match(orb,/width: 36px; height: 36px/);
  assert.match(orb,/background: radial-gradient[^]*linear-gradient\(145deg/);
  assert.match(orb,/box-shadow: inset/);
  assert.match(orb,/\.assistant-orb-chevron\s*\{[^}]*opacity: 0/);
  assert.match(orb,/\.assistant-orb-energy\s*\{[^}]*mask-image: radial-gradient[^}]*pointer-events: none/);
  assert.match(orb,/\.assistant-collapse:is\(:hover, :focus-visible\) \.assistant-orb-core\s*\{ opacity: 0/);
  assert.match(orb,/\.assistant-collapse:is\(:hover, :focus-visible\) \.assistant-orb-chevron\s*\{ opacity: 1/);
  assert.match(orb,/\.ai-collapsed \.assistant-orb-chevron\s*\{ transform: rotate\(180deg\)/);
  assert.match(orb,/\.assistant-orb-unread\s*\{[^}]*background: var\(--brand-teal\)/);
  assert.match(orb,/:root\[data-theme="light"\] \.assistant-orb/);
  assert.match(css,/\.assistant-collapse::before\s*\{[^}]*pointer-events: none; animation: assistant-orb-breathe/);
  assert.match(css,/\.assistant-workspace \.assistant-collapse\s*\{[^}]*width: 46px; height: 46px/);
  assert.match(css,/\.assistant-workspace :focus-visible\s*\{ outline: 2px solid var\(--brand-link\)/);
});

test('orb ambience uses slow decorative motion without animating layout or flashing',()=>{
  const css=read('../src/assistant.css');
  assert.match(css,/animation: assistant-orb-breathe 4\.6s ease-in-out infinite/);
  assert.match(css,/animation: assistant-orb-drift 10s linear infinite/);
  assert.match(css,/animation: assistant-orb-orbit 12s linear infinite/);
  assert.match(css,/linear-gradient\(145deg, #203f51, #142c42 55%, #0d192e\)/);
  assert.match(css,/\.assistant-collapse::before\s*\{[^}]*inset: -9px;[^}]*pointer-events: none/);
  assert.match(css,/\.assistant-collapse::after\s*\{[^}]*mask-image: radial-gradient[^}]*pointer-events: none/);
  for(const name of ['breathe','drift','orbit']) {
    const frames=css.match(new RegExp(`@keyframes assistant-orb-${name} \\{([^]*?)\\} \\}`))?.[1];
    assert.ok(frames);assert.doesNotMatch(frames,/\b(width|height|top|left|right|bottom|filter|box-shadow):/);
  }
  assert.match(css,/:root\[data-theme="light"\] \.assistant-collapse::before/);
});

test('workspace transitions and send decorations respect reduced motion',()=>{
  const css=read('../src/assistant.css');
  const reduced=css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced,/\.assistant-workspace\.is-unified \{ transition: none;/);
  assert.match(reduced,/\.assistant-send-pending i \{ animation: none;/);
  assert.match(reduced,/\.assistant-collapse::before \{ animation: none;/);
  assert.match(reduced,/\.assistant-collapse::after \{ animation: none; transition: none;/);
  assert.match(reduced,/\.assistant-orb-energy \{ animation: none;/);
  assert.match(reduced,/\.assistant-collapse:is\(:hover, :focus-visible, :active\) \.assistant-orb \{ transform: none;/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)\s*\{ \.assistant-workspace \*\s*\{[^}]*transition: none !important/);
  assert.match(css,/\.assistant-input-actions\s*\{[^}]*background: transparent;[^}]*box-shadow: none/);
  assert.doesNotMatch(css,/writing-mode: vertical-rl/);
});
