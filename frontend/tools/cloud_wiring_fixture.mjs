// Test-only renderer of the actual component; never submits a cloud request.
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/cloudWiring.ts', import.meta.url), 'utf8');
const library = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText;
const libraryUrl = `data:text/javascript;base64,${Buffer.from(library).toString('base64')}`;
export const cloudWiring = await import(libraryUrl);

export async function renderDetails(result, locale, overrides = {}) {
  const component = readFileSync(new URL('../src/components/CloudWiringDetails.tsx', import.meta.url), 'utf8');
  let js = ts.transpileModule(component, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  js = js.replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve('react/jsx-runtime')))
    .replaceAll('"../lib/cloudWiring"', JSON.stringify(libraryUrl))
    .replace(/import \{ useMakerText \} from "\.\.\/lib\/useMaker";/,
      `const useMakerText = () => (zh, en) => ${JSON.stringify(locale)} === 'zh-TW' ? zh : en;`);
  const {CloudWiringDetails} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  return renderToStaticMarkup(createElement(CloudWiringDetails, {
    job: {status: 'completed', result, images: []}, stale: false,
    target: {componentId: 'hc-sr04', componentPin: 'GND', boardLabel: 'Pin 6 · GND'}, ...overrides,
  }));
}

export const resultFixture = {
  verdict: 'uncertain', authority: 'visual_advisory', electrical_verified: false, same_wire: 'uncertain',
  summary: 'Fixture: colors visible, path obscured',
  board_endpoint: {state: 'uncertain', observed_pin: null, evidence: 'Fixture: exact Pi pin unclear'},
  component_endpoint: {state: 'target', observed_pin: 'GND', evidence: 'Fixture: module pin visible'},
  limitations: 'Fixture only, not a camera verdict',
  wire_colors: {
    board: {name: 'brown', visibility: 'clear', evidence: 'Fixture: brown insulation'},
    component: {name: 'orange', visibility: 'partial', evidence: 'Fixture: orange insulation'},
    comparison: 'uncertain', evidence: 'Fixture: color cast'},
  wire_path: {visibility: 'partially_visible', evidence: 'Fixture: obstruction in overview'},
};
