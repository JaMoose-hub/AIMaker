// Offline UI checks using the bundled Playwright runtime and an isolated Chrome profile.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.POC_PLAYWRIGHT_MODULE ||
  'C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

async function main() {
  const output = path.resolve(process.argv[2]);
  const expected = JSON.parse(fs.readFileSync(path.join(output, 'markers.json'), 'utf8'));
  const firstCount = expected.images[0].markers.length;
  const artifacts = path.join(output, 'browser-check');
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.POC_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  const context = await browser.newContext({ viewport: { width: 1480, height: 1120 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  try {
    await page.goto(pathToFileURL(path.join(output, 'index.html')).href, { waitUntil: 'load' });
    await page.waitForFunction(() => typeof ready !== 'undefined' && ready === true);
    assert.equal(await page.locator('#markerList button').count(), firstCount);
    assert(await page.evaluate(() => state.images.every(img => img.markers.every(m => m.physical_pin === null && m.reviewed === false))));
    assert.equal(await page.locator('#mainCanvas').evaluate(canvas => canvas.width), 2880);
    assert.equal(await page.locator('#physicalPin').inputValue(), '');
    assert.equal(await page.locator('#hintToggle').isChecked(), false);
    if (expected.cloud_called) {
      assert.match(await page.locator('#cloudRunInfo').textContent(), new RegExp(expected.cloud_run.model));
      assert.equal(await page.locator('#cloudColorRow').isVisible(), true);
      assert(await page.evaluate(() => state.images.every(img => img.markers.every(m => m.cloud_observation))));
    }
    await page.screenshot({ path: path.join(artifacts, 'desktop.png'), fullPage: true });

    await page.locator('#physicalPin').fill('12');
    await page.locator('#physicalPin').press('Tab');
    await page.locator('#reviewed').check();
    assert.equal(await page.locator('#reviewed').isChecked(), true);
    const before = await page.evaluate(() => ({ ...selected() }));
    // The taller cloud evidence panel scrolls the review checkbox into view;
    // return to the image before sending viewport mouse coordinates.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(50);
    const box = await page.locator('#mainCanvas').boundingBox();
    const startX = box.x + before.x / 2880 * box.width;
    const startY = box.y + before.y / 3840 * box.height;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 28, startY + 18, { steps: 8 });
    await page.mouse.up();
    const after = await page.evaluate(() => ({ ...selected() }));
    assert.notEqual(after.x, before.x);
    assert.equal(after.reviewed, false, 'Moving a marker must invalidate human pin review');
    assert.equal(await page.locator('#reviewed').isChecked(), false);

    await page.locator('#mainCanvas').click({ position: { x: box.width * .30, y: box.height * .30 } });
    assert.equal(await page.locator('#markerList button').count(), firstCount + 1);
    await page.locator('#deleteMarker').click();
    assert.equal(await page.locator('#markerList button').count(), firstCount);

    const downloadJson = page.waitForEvent('download');
    await page.locator('#exportJson').click();
    const jsonDownload = await downloadJson;
    const jsonPath = path.join(artifacts, 'markers-edited.json');
    await jsonDownload.saveAs(jsonPath);
    const downloaded = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    assert.equal(downloaded.images.length, 2);
    assert.equal(downloaded.images[0].markers[0].physical_pin, 12);
    assert.equal(downloaded.images[0].markers[0].reviewed, false);
    assert(!downloaded.images[0].data_url, 'Metadata download must not duplicate photo pixels');
    if (expected.cloud_called) {
      assert.equal(downloaded.cloud_run.model, expected.cloud_run.model);
      assert.deepEqual(downloaded.images[0].markers[0].cloud_observation, expected.images[0].markers[0].cloud_observation);
    }

    const bad = structuredClone(downloaded);
    bad.images[0].sha256 = '0'.repeat(64);
    const badPath = path.join(artifacts, 'wrong-photo.json');
    fs.writeFileSync(badPath, JSON.stringify(bad));
    await page.locator('#jsonFile').setInputFiles(badPath);
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('匯入失敗'));
    assert.match(await page.locator('#status').textContent(), /SHA-256/);
    assert.equal(await page.locator('#physicalPin').inputValue(), '12');

    const invalid = structuredClone(downloaded);
    invalid.images[0].markers[0].physical_pin = null;
    invalid.images[0].markers[0].reviewed = true;
    const invalidPath = path.join(artifacts, 'invalid-review.json');
    fs.writeFileSync(invalidPath, JSON.stringify(invalid));
    await page.locator('#jsonFile').setInputFiles(invalidPath);
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('匯入失敗'));
    assert.match(await page.locator('#status').textContent(), /核對|核實|腳號/);

    await page.locator('#resetBtn').click();
    assert.equal(await page.locator('#physicalPin').inputValue(), '');
    await page.locator('#jsonFile').setInputFiles(jsonPath);
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('已匯入'));
    assert.equal(await page.locator('#physicalPin').inputValue(), '12');

    for (const [button, filename] of [['exportPng', 'ai-material.png'], ['exportCrop', 'raw-crop.png'], ['exportPrompt', 'ai-prompt.txt']]) {
      const pending = page.waitForEvent('download');
      await page.locator('#' + button).click();
      await (await pending).saveAs(path.join(artifacts, filename));
      assert(fs.statSync(path.join(artifacts, filename)).size > 50);
    }
    const cropEvidence = await page.evaluate(() => ({
      rect: cropRect(selected()), image_id: imageState().id,
      rawColor: sampleColor(selected()), marker: selected()
    }));
    fs.writeFileSync(path.join(artifacts, 'crop-evidence.json'), JSON.stringify(cropEvidence, null, 2));

    await page.locator('#viewSelect').selectOption('1');
    assert.equal(await page.locator('#markerList button').count(), expected.images[1].markers.length);
    await page.screenshot({ path: path.join(artifacts, 'outside-view.png'), fullPage: true });
    assert.equal(await page.locator('#mainCanvas').evaluate(canvas => canvas.width), 3840);
    assert.equal(await page.locator('#hintToggle').isChecked(), false);
    if (expected.images[1].pin_hints.length) {
      await page.locator('#hintToggle').check();
      assert.match(await page.locator('#status').textContent(), /未核實|投影/);
      await page.locator('#hintToggle').uncheck();
    } else {
      assert(await page.locator('#hintToggle').isDisabled());
    }
    await page.locator('#overlayToggle').uncheck();
    await page.locator('#overlayToggle').check();

    await page.locator('#resetBtn').click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(200);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile page must not overflow horizontally');
    await page.screenshot({ path: path.join(artifacts, 'mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    const report = { passed: true, console_errors: errors, checks: [
      'offline load, prelabel counts, unconfirmed pins and source dimensions', 'drag invalidates human pin review', 'add/delete markers',
      'PNG/crop/JSON/prompt downloads', 'wrong-photo import rejected', 'invalid review rejected',
      'valid JSON replay', 'photo switching and diagnostic hints', 'mobile layout'
    ] };
    fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
