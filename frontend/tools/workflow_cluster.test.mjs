import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import postcss from 'postcss';

const css=postcss.parse(readFileSync(new URL('../src/tinkro.css',import.meta.url),'utf8'));
const scope='.app.tinkro-theme:not(.display-mode-active)';
const properties=(selector,media)=>{
  const result={};
  css.walkRules(selector,rule=>{
    if((media===null&&rule.parent.type==='root')||
      (rule.parent.type==='atrule'&&rule.parent.name==='media'&&rule.parent.params===media)) {
      rule.walkDecls(declaration=>result[declaration.prop]=declaration.value);
    }
  });
  return result;
};

test('desktop workflow spreads three steps across a bounded centered header group',()=>{
  const media='(min-width: 961px)';
  const nav=properties(scope+' .maker-header-main .maker-nav',media);
  assert.equal(nav.display,'grid');
  assert.equal(nav.flex,'1 1 0');
  assert.equal(nav['max-width'],'560px','spread the steps without consuming the utility controls');
  assert.equal(nav['margin-inline'],'auto');
  assert.equal(nav.gap,'28px');
  const button=properties(scope+' .maker-header-main .maker-nav button',media);
  assert.equal(button['white-space'],'nowrap');
  assert.equal(properties(scope+' .maker-header-main',media).gap,'32px');
  assert.equal(properties(scope+' .maker-header-integrated',null)['grid-template-columns'],'minmax(0, 1fr) auto','tools stay in the right-hand column');
});

test('compact desktop treatment preserves the three-column touch layout and hit targets',()=>{
  assert.equal(properties(scope+' .maker-header-main .maker-nav',null)['grid-template-columns'],'repeat(3, minmax(0, 1fr))');
  assert.equal(properties(scope+' .maker-header-main .maker-nav button','(max-width: 960px)')['min-height'],'44px');
  assert.equal(properties(scope+' .maker-header-main .maker-nav','(max-width: 700px)')['flex-basis'],'100%');
});
