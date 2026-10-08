import test from 'node:test';
import assert from 'node:assert/strict';
import {designFor,maker,componentTests,renderGuide,renderTestCard} from './project_guide_fixture.mjs';

export function iconFixture() {
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  let session=maker.startProjectGuide(maker.emptyGuide());
  while(session.phase==='active') session=maker.confirmProjectWire(design,session);
  const run={id:'icons',project_id:design.id,revision:design.revision,component_id:'hc-sr04',
    guide_key:componentTests.componentTestKey(design,session,'hc-sr04'),outcome:'inconclusive',reason:'no_echo',
    created_at:Date.now()/1000,finished_at:Date.now()/1000+60,phase:'finished',reserved:false,invalidated:false,
    samples:{},logs:[],options:[]};
  return {design,session,embedded:true,floating:true,toolbar:true,onDebug(){throw Error('No implicit AI');},
    tests:{pending:false,status:{connected:true,active:null,results:[run]}}};
}
const buttons=html=>html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g)??[];
const iconButtons=html=>buttons(html).filter(button=>button.includes('guide-action-icon-button'));

test('bottom test actions have four concise visible labels plus icons and tooltips in both languages',async()=>{
  for(const locale of ['zh-TW','en']) {
    const f=iconFixture(),before=JSON.stringify(f);
    const icons=iconButtons(await renderGuide({...f,locale}));
    assert.equal(icons.length,4);
    const expected=locale==='en'?['Retest','Ask AI','Back','Test later']:['重測','AI 求助','返回','稍後測試'];
    for(const [index,button] of icons.entries()) {
      assert.match(button,/aria-label="[^"]+"/); assert.match(button,/title="[^"]+"/);
      assert.match(button,/<svg aria-hidden="true"/); assert.equal(button.replace(/<[^>]*>/g,''),expected[index]);
      assert.ok(button.match(/aria-label="([^"]+)"/)[1].includes(expected[index]),'accessible name includes the visible label');
    }
    assert.ok(icons.some(b=>b.includes(locale==='en'?'Test later · Continue':'稍後測試，繼續')));
    assert.match(icons[3],/guide-defer-test-action/);
    assert.doesNotMatch(icons[2],/guide-defer-test-action/);
    assert.equal(JSON.stringify(f),before);
  }
});
test('disconnected or busy test icons remain disabled and help eligibility is unchanged',async()=>{
  for(const connected of [true,false]) {
    const f=iconFixture(); f.tests.status.connected=connected; f.tests.pending=connected;
    const icons=iconButtons(await renderGuide(f));
    assert.match(icons.find(b=>b.includes('guide-secondary-test-action')),/disabled=""/);
    assert.match(icons.find(b=>b.includes('guide-secondary-test-action')),connected?/aria-busy="true"/:/title="連接 Pi 後測試"/);
  }
  const f=iconFixture(); f.tests.status.results[0].finished_at=1;
  assert.ok(!iconButtons(await renderGuide(f)).some(b=>b.includes('component-test-debug-action')));
});
test('final module and passed navigation have distinct accessible destinations',async()=>{
  const f=iconFixture(); f.session={...f.session,componentIndex:1,phase:'review',confirmed:Object.fromEntries(f.design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),mode:'camera',at:'saved'}]))};
  const originalRun=f.tests.status.results[0];
  for(const passed of [false,true]) {
    f.tests.status.results=passed?[{...originalRun,component_id:'mrd-tf240-8p-cs',outcome:'passed',guide_key:componentTests.componentTestKey(f.design,f.session,'mrd-tf240-8p-cs')}]:[];
    const html=await renderGuide(f);
    assert.match(html,passed?/aria-label="前往部署"/:/aria-label="稍後測試，前往部署"/);
    assert.equal(html.includes('guide-defer-test-action'),!passed,'deferred tests must not use the passed-navigation color');
  }
});
test('non-inline test pages keep text, and active sampling keeps explicit safety controls',async()=>{
  const f=iconFixture();
  assert.equal(iconButtons(await renderTestCard({...f,view:'all'})).length,0);
  const run=f.tests.status.results[0]; Object.assign(run,{reserved:true,phase:'awaiting_near',outcome:'running',reason:null}); f.tests.status.active=run;
  const html=await renderGuide(f);
  assert.match(html,/>準備好了，取樣 5 秒<\/button>/); assert.match(html,/>停止本次測試<\/button>/);
  assert.doesNotMatch(html,/component-test-debug-action/);
});
