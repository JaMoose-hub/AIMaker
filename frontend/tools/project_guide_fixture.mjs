// Render the actual guide components with real catalog/session helpers and
// deterministic hook inputs. No camera access, cloud calls or hardware actions.
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import {componentHeaderUrl} from './component_header_fixture.mjs';

export const catalog = JSON.parse(readFileSync(new URL('../../profiles/component-catalog.json', import.meta.url), 'utf8'));
const dataUrl = js => `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
function compile(path, replacements = {}) {
  const source = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
    .replace(/import catalog from [^;]+;/, `const catalog = ${JSON.stringify(catalog)};`);
  let js = ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  for (const [name, url] of Object.entries({react: import.meta.resolve('react'), 'react/jsx-runtime': import.meta.resolve('react/jsx-runtime'), ...replacements})) {
    js = js.replaceAll(JSON.stringify(name), JSON.stringify(url));
  }
  return dataUrl(js);
}
const makerUrl = compile('lib/maker.ts');
export const maker = await import(makerUrl);
const testsUrl = compile('lib/componentTests.ts', {'./maker':makerUrl});
export const componentTests = await import(testsUrl);
const guidesUrl = compile('lib/componentWiringGuides.ts');
const cloudUrl = compile('lib/cloudWiring.ts');
const piGuideUrl = compile('lib/piHeaderGuide.ts');
export const piGuide = await import(piGuideUrl);
export const board = JSON.parse(readFileSync(new URL('../../profiles/boards/raspberry-pi-5/board.json', import.meta.url), 'utf8'));

export function designFor(ids = ['hc-sr04']) {
  return {id: 'layout-fixture', revision: 1, source: 'demo', catalog_version: catalog.version,
    title: 'Layout fixture', summary: 'Not hardware evidence', component_ids: ids,
    wiring: ids.flatMap(id => catalog.modules.find(m => m.id === id).steps.map(s => ({...s, id: `${id}:${s.id}`, componentId: id}))),
    code: '', tests: [], features: [], instructions: [], unresolved: [], bom: []};
}

export async function renderGuide({design = designFor(), session = maker.initialMaker().guide,
  locale = 'zh-TW', check = {}, poseReady = true, cloudAI = {}, visible = true, tests = {}, capture = null, pinsById = new Map(board.pins.map(p => [p.id, p]))} = {}) {
  const textUrl = dataUrl(`export const useMakerText = () => (zh, en) => ${JSON.stringify(locale)} === 'zh-TW' ? zh : en;`);
  const messages = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`, import.meta.url), 'utf8'));
  const i18nUrl = dataUrl(`export const useI18n = () => ({locale: ${JSON.stringify(locale)},
    t:(key,params={})=>Object.entries(params).reduce((s,[k,v])=>s.replace('{'+k+'}',String(v)),(${JSON.stringify(messages)})[key]??key),
    tx: value => typeof value === 'string' ? value : value[${JSON.stringify(locale)}]});`);
  const compactUrl = compile('components/CompactGuide.tsx', {'../lib/useMaker': textUrl});
  const detailsUrl = compile('components/CloudWiringDetails.tsx', {'../lib/useMaker': textUrl, '../lib/cloudWiring': cloudUrl});
  const checkUrl = dataUrl(`export const calls=[]; export function useCloudWiringCheck(request, enabled) {
    calls.push({enabled}); return {stale:false, busy:false, ...${JSON.stringify(check)}, start(){throw Error('Rendering must never submit a cloud request');}};
  }`);
  const checkModule = await import(checkUrl);
  checkModule.calls.length = 0;
  const projectUrl = compile('components/ProjectGuidePanel.tsx', {
    '../lib/componentTests': testsUrl,
    '../lib/useComponentTests': dataUrl(`export const useComponentTests = () => ({status:{connected:true,active:null,results:[],test_busy:false},error:null,pending:false,...${JSON.stringify(tests)},start(){throw Error('No hardware action during render');},connect(){},action(){},invalidate(){}});`),
    './ComponentTestCard': compile('components/ComponentTestCard.tsx', {'../lib/useMaker':textUrl, '../lib/componentTests':testsUrl}),
    '../lib/componentHeaderGuide': componentHeaderUrl,
    './ComponentRowLocator': compile('components/ComponentRowLocator.tsx', {'../lib/i18n':i18nUrl, '../lib/componentHeaderGuide':componentHeaderUrl}),
    '../lib/piHeaderGuide': piGuideUrl,
    './PiRowLocator': compile('components/PiRowLocator.tsx', {'../lib/i18n':i18nUrl, '../lib/piHeaderGuide':piGuideUrl}),
    '../lib/useMaker': textUrl, '../lib/i18n': i18nUrl, '../lib/maker': makerUrl,
    '../lib/componentWiringGuides': guidesUrl, '../lib/cloudWiring': cloudUrl,
    './CompactGuide': compactUrl, './CloudWiringDetails': detailsUrl,
    '../lib/useGuidedPose': dataUrl(`export const useGuidedPose = () => ({strictReady: ${Boolean(poseReady)}});`),
    '../lib/useCloudWiringCheck': checkUrl,
  });
  const {ProjectGuidePanel} = await import(projectUrl);
  const html = renderToStaticMarkup(createElement(ProjectGuidePanel, {design, session, visible, pinsById, disabled: false,
    cloudAI: {model: 'fixture', effort: 'low', available: true, supportsImages: true, busy: false, ...cloudAI},
    onChange(){throw Error('Rendering must never change manual progress');}, onTargetChange(){}, onVisibleChange(){}, onDeploy(){},
  }));
  if (capture) capture.cloudReady = checkModule.calls.at(-1)?.enabled ?? false;
  return html;
}
