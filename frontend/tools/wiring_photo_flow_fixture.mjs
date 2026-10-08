import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';

export function flowModule(path, imports = {}) {
  const exports = {};
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const parsed = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  if (parsed.parseDiagnostics.length) throw Error(path + ': ' + parsed.parseDiagnostics.map(diagnostic => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')).join('\n'));
  const js = ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
  }}).outputText;
  new Function('React', 'require', 'exports', js)(React, name => {
    if (name in imports) return imports[name];
    throw Error(`Unexpected photo flow import: ${name}`);
  }, exports);
  return exports;
}
export const reviewHelpers = flowModule('../src/lib/wiringReview.ts');
export const expectedLocationHelpers = flowModule('../src/lib/wiringExpectedLocation.ts', {
  './wiringReview': reviewHelpers,
  '../../../profiles/boards/raspberry-pi-5/board.json': {default: JSON.parse(readFileSync(new URL('../../profiles/boards/raspberry-pi-5/board.json', import.meta.url), 'utf8'))},
  './piHeaderGuide': flowModule('../src/lib/piHeaderGuide.ts'),
});
export function expectedLocationComponent(language = 'en', hooks = React) {
  return flowModule('../src/components/WiringExpectedLocation.tsx', {
    react: hooks, '../lib/useMaker': {useMakerText: () => (zh, en) => language === 'en' ? en : zh},
    '../lib/wiringExpectedLocation': expectedLocationHelpers, './wiringExpectedLocation.css': {},
  });
}
export function framingGuide(language = 'en') {
  return flowModule('../src/components/WiringFramingGuide.tsx', {
    '../lib/useMaker': {useMakerText: () => (zh, en) => language === 'en' ? en : zh},
    '../lib/wiringReview': reviewHelpers,
  }).WiringFramingGuide;
}
export const photoFlow = flowModule('../src/lib/wiringPhotoFlow.ts', {'./wiringReview': reviewHelpers});
export function photoSequence(hooks = React, language = 'en') {
  return flowModule('../src/components/WiringPhotoSequence.tsx', {react: hooks,
    '../lib/useMaker': {useMakerText: () => (zh, en) => language === 'en' ? en : zh},
    '../lib/wiringReview': reviewHelpers, '../lib/wiringPhotoFlow': photoFlow,
  }).WiringPhotoSequence;
}
