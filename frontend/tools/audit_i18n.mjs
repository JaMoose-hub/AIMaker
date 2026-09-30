// Read-only inventory of Chinese literals outside bilingual UI helpers.
import {readFileSync,readdirSync,statSync} from 'node:fs';
import {join,relative,resolve} from 'node:path';
import ts from 'typescript';
const root=resolve(import.meta.dirname,'../src');
const han=/\p{Script=Han}/u;
const files=folder=>readdirSync(folder).flatMap(name=>{const path=join(folder,name);return statSync(path).isDirectory()?files(path):[path];});
function bilingual(node){
  for(let parent=node.parent;parent;parent=parent.parent){
    if(ts.isCallExpression(parent)&&['tr','tx','t'].includes(parent.expression.getText().split('.').at(-1)))return true;
    if(ts.isArrayLiteralExpression(parent)&&parent.elements.length===2&&parent.elements.every(ts.isStringLiteral)&&!han.test(parent.elements[1].text))return true;
    if(ts.isObjectLiteralExpression(parent)&&parent.properties.some(property=>ts.isPropertyAssignment(property)&&property.name.getText().replace(/["']/g,'')==='en'))return true;
  }
  return false;
}
const findings=[];
for(const path of files(root).filter(path=>/\.(tsx?|json)$/.test(path))){
  if(path.endsWith('json')){
    if(path.endsWith('en.json'))for(const [key,value]of Object.entries(JSON.parse(readFileSync(path,'utf8'))))if(han.test(value))findings.push({file:relative(root,path),key,text:value});
    continue;
  }
  const tree=ts.createSourceFile(path,readFileSync(path,'utf8'),ts.ScriptTarget.Latest,true,path.endsWith('tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
  function visit(node){
    if((ts.isStringLiteralLike(node)||ts.isJsxText(node)||ts.isTemplateHead(node)||ts.isTemplateMiddle(node)||ts.isTemplateTail(node))&&han.test(node.text)&&!bilingual(node)){
      const position=tree.getLineAndCharacterOfPosition(node.getStart(tree));
      findings.push({file:relative(root,path),line:position.line+1,text:node.text.trim().slice(0,150)});
    }
    ts.forEachChild(node,visit);
  }
  visit(tree);
}
console.log(JSON.stringify(findings,null,2));
