import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, loadConfigFromFile } from 'vite';

test('rebuilding retains the lazy chunks referenced by an already-open page', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tinkro-build-retention-'));
  const outDir = join(root, 'dist');
  const loaded = await loadConfigFromFile({ command: 'build', mode: 'production' }, fileURLToPath(new URL('../vite.config.ts', import.meta.url)));
  const config = { ...loaded.config, root, configFile: false, publicDir: false, logLevel: 'silent',
    build: { ...loaded.config.build, outDir, minify: false } };
  await writeFile(join(root, 'index.html'), '<script type="module" src="/main.js"></script>');
  await writeFile(join(root, 'main.js'), 'window.openPairing = () => import("./pairing.js");');
  await writeFile(join(root, 'pairing.js'), 'export const pairing = "first release";');
  await build(config);
  const names = await readdir(join(outDir, 'assets'));
  const prior = await Promise.all(names.map(async name => [name, await readFile(join(outDir, 'assets', name), 'utf8')]));
  const firstIndex = await readFile(join(outDir, 'index.html'), 'utf8');
  await writeFile(join(root, 'pairing.js'), 'export const pairing = "second release";');
  await build(config);
  assert.notEqual(await readFile(join(outDir, 'index.html'), 'utf8'), firstIndex);
  for (const [name, content] of prior) assert.equal(await readFile(join(outDir, 'assets', name), 'utf8'), content);
});
