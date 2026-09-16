import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const zh = JSON.parse(readFileSync(join(root, "src/locales/zh-TW.json"), "utf8"));
const en = JSON.parse(readFileSync(join(root, "src/locales/en.json"), "utf8"));
const zhKeys = Object.keys(zh).sort();
const enKeys = Object.keys(en).sort();
const missingEn = zhKeys.filter((key) => !(key in en));
const missingZh = enKeys.filter((key) => !(key in zh));
const issues = [];
if (missingEn.length) issues.push(`missing in en: ${missingEn.join(", ")}`);
if (missingZh.length) issues.push(`missing in zh-TW: ${missingZh.join(", ")}`);
if (zhKeys.length < 437) issues.push(`locale catalog unexpectedly shrank to ${zhKeys.length} keys`);

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
}

if (issues.length) {
  console.error(issues.join("\n"));
  process.exit(1);
}
console.log(`i18n parity OK: ${zhKeys.length} keys in zh-TW and en; no literal tooltip/ARIA/placeholder/alt text`);
