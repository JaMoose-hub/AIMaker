import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../src/assistant.css', import.meta.url), 'utf8');
const component = readFileSync(new URL('../src/components/AssistantWorkspace.tsx', import.meta.url), 'utf8');

test('collapsed desktop AI reserves no sidebar width and has no interactive resize handle', () => {
  assert.match(css, /\.assistant-workspace\.is-unified\.ai-collapsed\s*\{ grid-template-columns: minmax\(0, 1fr\) 0 0;/);
  assert.match(css, /@media \(min-width: 1100px\)[^]*?\.ai-collapsed > \.assistant-resizer \{ display: none;/);
  assert.doesNotMatch(css, /grid-template-columns: minmax\(0, 1fr\) 8px 64px/);
});

test('collapsed entry has a bounded footprint and only its button intercepts clicks', () => {
  assert.match(css, /\.is-unified\.ai-collapsed > \.assistant-chat-surface\s*\{[^}]*position: absolute;[^}]*width: 46px; height: 66px;[^}]*pointer-events: none;/);
  assert.match(css, /\.is-unified\.ai-collapsed \.assistant-collapse\s*\{[^}]*pointer-events: auto;/);
  assert.match(css, /@media \(max-width: 1099px\)[^]*?\.assistant-chat-surface \{ flex: 1;/);
});

test('collapse retains the existing conversation, toggle and mobile tabs without a second owner', () => {
  assert.equal((component.match(/id="assistant-chat-content"/g) ?? []).length, 1);
  assert.match(component, /<div id="assistant-chat-content" className="assistant-chat-content">\{assistant\}<\/div>/);
  assert.match(component, /onClick=\{\(\) => onAiOpen\(!aiOpen\)\} aria-expanded=\{aiOpen\}/);
  assert.match(component, /aria-controls="assistant-chat-surface"/);
});
