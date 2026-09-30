import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {maker,designFor} from './project_guide_fixture.mjs';
import {systemText} from './system_text_fixture.mjs';
import ts from 'typescript';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const han=/\p{Script=Han}/u;

test('all shared English system translations and locale values are free of Chinese',()=>{
  for(const [zh,en]of JSON.parse(read('../../profiles/ui-system-messages.json'))){
    assert(!han.test(en),en);assert.equal(systemText(zh,'en'),en);
  }
  for(const [key,value]of Object.entries(JSON.parse(read('../src/locales/en.json'))))assert(!han.test(value),key);
});

test('known status and material names follow both language switches without altering free-form text',()=>{
  assert.equal(systemText('本次 AI 協作除錯已停止。','en'),'This AI debugging check has stopped.');
  assert.equal(systemText('輪子 / Wheel','en'),'Wheel');
  assert.equal(systemText('Wheel','zh-TW'),'輪子 / Wheel');
  assert.equal(systemText('我自己寫的需求和 1234 螢幕文字','en'),'我自己寫的需求和 1234 螢幕文字');
});

test('only untouched starter prompts change language, preserving all project and guide references',()=>{
  const state={...maker.initialMaker(),design:designFor(['hc-sr04']),conversation:[{role:'user',text:'保留歷史'}]};
  const en=maker.localizeStarterPrompt(state,'en');
  assert.equal(en.prompt,maker.defaultPromptEn);assert(!han.test(en.prompt));
  for(const key of Object.keys(state).filter(key=>key!=='prompt'))assert.equal(en[key],state[key]);
  assert.equal(maker.localizeStarterPrompt(en,'zh-TW').prompt,maker.defaultPrompt);
  assert.equal(maker.localizeStarterPrompt(en,'en'),en);
  for(const prompt of ['', '使用者中文草稿', `${maker.defaultPrompt}\n我的補充`]){
    const custom={...state,prompt};assert.equal(maker.localizeStarterPrompt(custom,'en'),custom);
  }
  const busy={...state,aiJobId:'existing-job'};assert.equal(maker.localizeStarterPrompt(busy,'en'),busy);
});

test('design requests always carry the current language without rewriting history',()=>{
  const state={...maker.initialMaker(),conversation:[{role:'assistant',text:'先前的中文回覆'}]};
  for(const locale of ['zh-TW','en']){
    const body=maker.designRequest(state,locale,null);
    assert.equal(body.locale,locale);assert.deepEqual(body.conversation,state.conversation);
  }
});

test('chat, photo, component test and diagnostic timestamps always use explicit UI locale',()=>{
  let calls=0;
  for(const name of ['AiDebugPanel','PhotoEvidenceCard','ComponentTestCard','DebugPage']){
    const tree=ts.createSourceFile(`${name}.tsx`,read(`../src/components/${name}.tsx`),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    function visit(node){
      if(ts.isCallExpression(node)&&ts.isPropertyAccessExpression(node.expression)&&
        /^(toLocaleString|toLocaleTimeString)$/.test(node.expression.name.text)){
        assert.equal(node.arguments.length,1,`${name}: timestamp must follow UI locale`);calls++;
      }
      ts.forEachChild(node,visit);
    }
    visit(tree);
  }
  assert.equal(calls,8);
});
