import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as ReactDOM from 'react-dom';

// Existing panel suites load the production entry policy and component rather
// than duplicating recommendation behavior in a test-only implementation.
function compile(path, imports = {}) {
  const exports = {};
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
  }}).outputText;
  new Function('React', 'require', 'exports', code)(React, name => {
    if (name in imports) return imports[name];
    throw new Error(`Unexpected wiring entry fixture import: ${name}`);
  }, exports);
  return exports;
}

export const wiringEntryHelpers = compile('../src/lib/wiringReviewEntry.ts');
export const {recommendWiringReview} = wiringEntryHelpers;
export const {WiringReviewEntry} = compile('../src/components/WiringReviewEntry.tsx', {
  react: React,
  'react-dom': ReactDOM,
  '../lib/useMaker': {useMakerText: () => zh => zh},
  '../lib/wiringReviewEntry': wiringEntryHelpers,
  './wiringReview.css': {},
});
