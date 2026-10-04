import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {designFor,maker,renderGuide} from './project_guide_fixture.mjs';

test('attention dock keeps real endpoints and short action copy for both modules and locales',async()=>{
  for(const cid of ['hc-sr04','mrd-tf240-8p-cs'])for(const locale of ['zh-TW','en']) {
    const design=designFor([cid]),session=maker.startProjectGuide(maker.emptyGuide());
    const before=structuredClone(session);
    const html=await renderGuide({design,session,locale,floating:true,embedded:true});
    const card=html.match(/<section[^>]*guide-current-step[^>]*>([\s\S]*?)<\/section>/)?.[1];
    assert.ok(card);
    assert.match(card,/<strong>GND<\/strong>/);
    assert.match(card,/<strong>Pin (6|20)<\/strong>/);
    assert.match(card,/>Pi 5<\/span>/);
    assert.match(card,/aria-label="(第 1／[47] 條接線|Wire 1 of [47])"/);
    assert.match(card,/<svg aria-hidden="true"/);
    assert.ok(card.includes(locale==='en'?'CONNECT NOW':'接這條線'));
    assert.match(html,/guide-primary-action/);
    assert.ok(html.includes(locale==='en'?'Connected · Next':'接好了，下一步'));
    if(cid==='mrd-tf240-8p-cs')assert.ok(card.includes('BLK'));
    assert.doesNotMatch(html,/data-view="dock"/);
    assert.deepEqual(session,before);
  }
});

test('non-dock guides retain their existing descriptive copy',async()=>{
  const html=await renderGuide({session:maker.startProjectGuide(maker.emptyGuide())});
  assert.match(html,/這一步要接/);
  assert.match(html,/Raspberry Pi 5 · 實體腳位/);
  assert.match(html,/零件端第 4 腳/);
  assert.match(html,/我已接好，下一步/);
  assert.doesNotMatch(html,/guide-current-step/);
});

test('attention is scoped to the active dock and respects reduced motion without layout movement',()=>{
  const css=readFileSync(new URL('../src/floatingGuide.css',import.meta.url),'utf8');
  assert.match(css,/:has\(\.compact-guide\.active\)[\s\S]*var\(--bg-panel\) 56%, transparent/);
  assert.match(css,/guide-current-step\s*\{[^}]*border-left: 3px solid var\(--brand-teal\)/s);
  const motion=css.match(/@keyframes guide-step-arrive\s*\{([\s\S]*?)\n\}/)?.[1];
  assert.ok(motion);
  assert.doesNotMatch(motion,/transform|height|width|margin/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*guide-current-step \{ animation: none;/s);
  assert.match(css,/animation: guide-step-arrive \.65s ease-out both;/);
});
