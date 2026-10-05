import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Check the actual error mapper without mounting a phone, opening IndexedDB,
// uploading a file, or connecting to the user's running service.
const source = readFileSync(new URL('../src/lib/useMobileBrowser.ts', import.meta.url), 'utf8');
const start = source.indexOf('const EXPIRED_SESSION_MESSAGE');
const end = source.indexOf('const browserForeground');
const code = ts.transpileModule(source.slice(start, end), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const errorText = new Function('expiredBrowserSession', `${code}\nreturn errorText;`)(() => false);

test('collection rejection explains all three views, guided submission and retained attachments', () => {
  const cause = Object.assign(Error('409'), { detail: 'wiring_photo_collection_in_progress' });
  const message = errorText(cause);
  for (const phrase of ['Pi 兩側', '零件接頭三張照片', '拍這張照片', '收齊後', '開始分析', '文字與附件已保留', '尚未進行分析']) {
    assert.ok(message.includes(phrase), phrase);
  }
});

test('analysis-busy and unrelated errors keep their existing handling', () => {
  assert.match(errorText({ detail: 'wiring_analysis_in_progress' }), /正在分析/);
  assert.equal(errorText(Error('network interrupted')), 'network interrupted');
});
