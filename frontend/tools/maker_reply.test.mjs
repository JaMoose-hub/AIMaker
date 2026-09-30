import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/lib/makerReply.ts',import.meta.url),'utf8');
const module=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {makerReplyPreview}=await import(`data:text/javascript;base64,${Buffer.from(module).toString('base64')}`);

test('the reported short reply stays one complete paragraph without redundant disclosure',()=>{
  const text='會保留現有距離監測與 20 cm 警告設定，改為上下雙層圓形壓克力桌面造型。小車圖示先列為待確認的顯示需求；現有螢幕流程僅確認 RGB 測試卡與距離、狀態文字。';
  assert.deepEqual(makerReplyPreview(text),{blocks:[{kind:'paragraph',text}],hasMore:false});
});

test('multiple ordinary sentences, blank lines and semicolons do not become lists',()=>{
  assert.deepEqual(makerReplyPreview('已修改。請看預覽；確認後才套用。\r\n\r\n接線仍待確認。'),{
    blocks:[{kind:'paragraph',text:'已修改。請看預覽；確認後才套用。'},{kind:'paragraph',text:'接線仍待確認。'}],hasMore:false});
  assert.deepEqual(makerReplyPreview('- 已修改造型'),{blocks:[{kind:'paragraph',text:'已修改造型'}],hasMore:false});
});

test('authored bullets and an introduction retain their format, without inventing a summary',()=>{
  assert.deepEqual(makerReplyPreview('可選兩種造型：\n- 圓盤\n• 方盒\n\n功能不變。'),{
    blocks:[{kind:'paragraph',text:'可選兩種造型：'},{kind:'list',ordered:false,items:[{text:'圓盤'},{text:'方盒'}]},
      {kind:'paragraph',text:'功能不變。'}],hasMore:false});
});

test('ordered step numbers stay literal even when a later warning must remain visible',()=>{
  const text='2. 查看預覽\n3. 確認造型\n4. 其他細節\n7. 未確認電壓前不要通電。';
  assert.deepEqual(makerReplyPreview(text),{blocks:[{kind:'list',ordered:true,items:[
    {text:'查看預覽',ordinal:2},{text:'確認造型',ordinal:3},{text:'未確認電壓前不要通電。',ordinal:7}]}],hasMore:true});
});

test('a long reply is literal and bounded, with a later critical condition intact',()=>{
  const text='作品概念'.repeat(75)+'。其他細節。尚未完成測試。未確認電壓前不要通電。';
  const preview=makerReplyPreview(text);
  assert.equal(preview.hasMore,true);
  assert.equal(preview.blocks.length,1);
  assert.equal(preview.blocks[0].kind,'paragraph');
  assert.match(preview.blocks[0].text,/… 未確認電壓前不要通電。$/);
  assert(preview.blocks[0].text.length<=220);
});

test('essential caveats are not clipped or duplicated just to meet the length target',()=>{
  const text='電壓未確認，'+ '不可通電。'.repeat(50);
  // Short safety sentences may require more than the normal preview budget.
  const preview=makerReplyPreview(text);
  assert(preview.hasMore);
  assert(preview.blocks.every(block=>block.kind==='paragraph'));
  assert.doesNotMatch(preview.blocks[0].text,/…/);
  const condition='未確認電壓前不要通電：'+ '完整條件'.repeat(70);
  assert.deepEqual(makerReplyPreview(condition),{blocks:[{kind:'paragraph',text:condition}],hasMore:false});
});

test('code remains available in the full reply instead of being mistaken for steps',()=>{
  const preview=makerReplyPreview('先看現象。\n```python\n1. not a step\n- not a bullet\n```');
  assert.deepEqual(preview,{blocks:[{kind:'paragraph',text:'先看現象。'}],hasMore:true});
  assert.deepEqual(makerReplyPreview('```python\nprint(1)\n```'),{blocks:[],hasMore:true});
  assert.deepEqual(makerReplyPreview('  \r\n'),{blocks:[],hasMore:false});
});
