import {readFileSync} from 'node:fs';
import ts from 'typescript';

const messages=readFileSync(new URL('../../profiles/ui-system-messages.json',import.meta.url),'utf8');
const source=readFileSync(new URL('../src/lib/systemText.ts',import.meta.url),'utf8')
  .replace(/^import messages[^\n]+/m,`const messages=${messages};`);
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
export const systemTextUrl=`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
export const {systemText}=await import(systemTextUrl);
