import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
test('design and debug chat distinguish messages from notices with consistent bubbles',()=>{
  const maker=read('../src/maker.css'),theme=read('../src/tinkro.css');
  assert.match(maker,/\.maker-assistant \.maker-conversation\s*\{[^}]*display: flex; flex-direction: column/);
  assert.match(maker,/\.maker-message\.user\s*\{[^}]*align-self: flex-end/);
  assert.match(theme,/:is\(\.maker-message, \.ai-debug-message\)\s*\{[^}]*border: 1px solid[^}]*border-radius: 16px 16px 16px 4px/);
  assert.match(theme,/:is\(\.maker-message\.user, \.ai-debug-message\.is-user\)\s*\{[^}]*border-radius: 16px 16px 4px 16px/);
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
