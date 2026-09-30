import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";

const root = resolve(import.meta.dirname, "..");
const zh = JSON.parse(readFileSync(join(root, "src/locales/zh-TW.json"), "utf8"));
const en = JSON.parse(readFileSync(join(root, "src/locales/en.json"), "utf8"));
const zhKeys = Object.keys(zh).sort();
const enKeys = Object.keys(en).sort();
const missingEn = zhKeys.filter((key) => !(key in en));
const missingZh = enKeys.filter((key) => !(key in zh));
const issues = [];
for (const locale of ["en", "zh-TW"]) {
  const path = join(root, `src/locales/${locale}.json`);
  const json = ts.parseJsonText(path, readFileSync(path, "utf8"));
  const keys = new Set();
  for (const property of json.statements[0].expression.properties) {
    const key = property.name.text;
    if (keys.has(key)) issues.push(`${locale}: duplicate translation key ${key}`);
    keys.add(key);
  }
}
if (missingEn.length) issues.push(`missing in en: ${missingEn.join(", ")}`);
if (missingZh.length) issues.push(`missing in zh-TW: ${missingZh.join(", ")}`);
if (zhKeys.length < 437) issues.push(`locale catalog unexpectedly shrank to ${zhKeys.length} keys`);
for (const [key, value] of Object.entries(en)) {
  if (/\p{Script=Han}/u.test(value)) issues.push(`English translation contains Chinese: ${key}`);
}

function filesBelow(folder) {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    return statSync(path).isDirectory() ? filesBelow(path) : [path];
  });
}

const literalAttribute = /\b(?:title|aria-label|placeholder|alt)\s*=\s*["'][^"']+["']/g;
for (const path of filesBelow(join(root, "src")).filter((item) => item.endsWith(".tsx"))) {
  const source = readFileSync(path, "utf8");
  for (const match of source.matchAll(literalAttribute)) {
    issues.push(`${relative(root, path)}: hardcoded user-facing attribute ${match[0]}`);
  }
  const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  function visit(node) {
    if (ts.isJsxText(node) && /\p{Script=Han}/u.test(node.text)) {
      const line = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
      issues.push(`${relative(root, path)}:${line}: untranslated Chinese JSX text`);
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
}

if (issues.length) {
  console.error(issues.join("\n"));
  process.exit(1);
}
console.log(`i18n parity OK: ${zhKeys.length} keys in zh-TW and en; no literal tooltip/ARIA/placeholder/alt text`);
