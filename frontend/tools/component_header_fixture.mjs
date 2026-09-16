import {readFileSync} from 'node:fs';
import ts from 'typescript';

export const dataUrl = js => `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
export function compileHeaderFile(path, replacements = {}) {
  let source = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
  // Embed the real profiles into the Node fixture, exactly as Vite bundles JSON.
  for (const [name, id] of [['ultrasonic','hc-sr04'],['screen','mrd-tf240-8p-cs']]) {
    const json = readFileSync(new URL(`../../profiles/components/${id}/vision_profile.json`, import.meta.url), 'utf8');
    source = source.replace(new RegExp(`import ${name} from [^;]+;`), `const ${name} = ${json};`);
  }
  let js = ts.transpileModule(source, {compilerOptions: {target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  for (const [key,value] of Object.entries({react:import.meta.resolve('react'),'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),...replacements})) js=js.replaceAll(JSON.stringify(key),JSON.stringify(value));
  return dataUrl(js);
}
export const componentHeaderUrl = compileHeaderFile('lib/componentHeaderGuide.ts');
