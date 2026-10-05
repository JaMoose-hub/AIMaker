import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import postcss from 'postcss';

const source=readFileSync(new URL('../src/assistant.css',import.meta.url),'utf8');
const css=postcss.parse(source);
const selector='.app:not(.display-mode-active) .is-unified .deploy-workspace';
const layout={};
css.walkRules(rule=>{
  if(rule.selector===selector)rule.walkDecls(decl=>{layout[decl.prop]=decl.value;});
});

test('unified deployment restores equal, stretch-aligned code and output columns',()=>{
  assert.equal(layout.display,'grid');
  assert.equal(layout['align-items'],'stretch');
  assert.equal(layout.gap,'10px');
  assert.notEqual(layout['flex-direction'],'column');
});

test('deployment columns respond to available pane width without overflowing phones',()=>{
  assert.equal(layout['grid-template-columns'],'repeat(auto-fit, minmax(min(100%, 360px), 1fr))');
  const legacy=readFileSync(new URL('../src/debug.css',import.meta.url),'utf8');
  assert.match(legacy,/\.deploy-primary-column,\.deploy-results-column\s*\{[^}]*min-width:0/);
});

test('code remains before output and no component is moved or conditionally remounted',()=>{
  const panel=readFileSync(new URL('../src/components/PiDeployPanel.tsx',import.meta.url),'utf8');
  assert.ok(panel.indexOf('className="deploy-primary-column"')<panel.indexOf('className={`deploy-results-column'));
  assert.match(panel,/<textarea id="pi-python-code" className="pi-code-editor"/);
  assert.match(panel,/<pre\s[^>]*className="pi-console"/);
});

test('deployment fills spare pane height while editors and logs can grow and scroll',()=>{
  const properties=selector=>{
    const values={};css.walkRules(selector,rule=>rule.walkDecls(decl=>values[decl.prop]=decl.value));return values;
  };
  const scope='.app:not(.display-mode-active) .is-unified .maker-deploy-main';
  assert.equal(properties(scope).display,'flex');
  assert.equal(properties(scope+' > .pi-deploy-panel').flex,'1 0 auto');
  assert.equal(properties(scope+' .deploy-workspace').flex,'1 0 auto');
  assert.equal(properties(scope+' .deploy-code-card textarea').flex,'1 1 var(--editor-height, 200px)');
  assert.equal(properties(scope+' .deploy-code-card textarea')['min-height'],'max(160px, var(--editor-height, 200px))');
  assert.equal(properties(scope+' .pi-console')['max-height'],'none');
});
