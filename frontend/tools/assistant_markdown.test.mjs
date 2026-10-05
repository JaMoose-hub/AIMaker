import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {markdownFixture} from './assistant_markdown_fixture.mjs';

function render(text,locale='zh-TW') {
  const {AssistantMarkdown}=markdownFixture(locale);
  return renderToStaticMarkup(React.createElement(AssistantMarkdown,{text}));
}

test('hardware comparison renders five real columns and three complete evidence rows',()=>{
  const html=render('| 零件 / demo 規格 | 判定 | 本次照片依據 | 缺少的規格 / 證據 | 下一個核對方式 |\n|---|---|---|---|---|\n| Raspberry Pi 5 | 符合（型號） | 可讀到 16GB RAM | 供電與功能未確認 | 核對包裝 |\n| HC-SR04+ / 3.3V | 疑似不同 | 照片標示 HC-SR04 | 3.3V ECHO 未確認 | 核對規格書 |\n| MRD_TFT240_8P_CS / ILI9341 | 無法確認 | 240×320 RGB | 控制器未確認 | 核對背面型號 |');
  assert.equal((html.match(/<th\b/g)||[]).length,5);
  assert.equal((html.match(/<td\b/g)||[]).length,15);
  assert.match(html,/<tbody>/);
  for(const text of ['Raspberry Pi 5','16GB RAM','3.3V ECHO 未確認','MRD_TFT240_8P_CS / ILI9341','控制器未確認'])assert.ok(html.includes(text));
  assert.match(html,/role="region" tabindex="0" aria-label="AI 回覆表格，可左右捲動"/);
  assert.doesNotMatch(html,/\|---\|/);
});

test('headings, nested lists, emphasis, inline pins and authored line breaks stay readable',()=>{
  const html=render('## 核對結果\n\n先看 **型號** 與 `Pin 6`。\n保留這行提醒。\n\n1. 先斷電\n2. 核對接頭\n   - GND\n   - *TRIG*\n\n> 不代表導通驗證');
  for(const fragment of ['<h2>核對結果</h2>','<strong>型號</strong>','<code>Pin 6</code>','<ol>','<ul>','<em>TRIG</em>','<blockquote>'])assert.ok(html.includes(fragment),fragment);
  assert.match(html,/。\n保留這行提醒。/);
});

test('fenced code retains whitespace and displays HTML as escaped code',()=>{
  const html=render('```python\nif ready:\n    print("<script>alert(1)</script>")\n```');
  assert.match(html,/<pre tabindex="0"/);
  assert.match(html,/class="language-python"/);
  assert.ok(html.includes('\n    print('));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.doesNotMatch(html,/<script>/);
});

test('HTML and dangerous link protocols cannot become executable elements',()=>{
  const html=render('<script>alert(1)</script>\n\n<img src="x" onerror="alert(2)">\n\n[bad](javascript:alert%281%29) [data](data:text/html,evil) [good](https://example.com/spec)');
  assert.doesNotMatch(html,/<script|<img|onerror=|href="(?:javascript|data):/i);
  assert.match(html,/<a href="https:\/\/example.com\/spec" target="_blank" rel="noopener noreferrer">good<\/a>/);
});

test('Markdown image URLs require a click instead of automatically fetching external media',()=>{
  const html=render('![規格照片](https://example.com/photo.png)');
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/<a href="https:\/\/example.com\/photo.png"[^>]*>規格照片<\/a>/);
});

test('GFM handles escaped pipes, alignment and read-only task lists',()=>{
  const html=render('| Pin | Description |\n|:---|---:|\n| `GND` | A \\| B |\n\n- [x] 型號已核對\n- [ ] 供電未確認','en');
  assert.match(html,/text-align:right/);
  assert.ok(html.includes('A | B'));
  assert.match(html,/type="checkbox" disabled="" checked=""/);
  assert.match(html,/aria-label="AI response table, scroll horizontally"/);
});
