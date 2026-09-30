import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import postcss from 'postcss';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../src/tinkro.css'));
const declarations = selector => {
  const values = {};
  css.walkRules(selector, rule => rule.walkDecls(d => { values[d.prop] = d.value; }));
  return values;
};
const scope = '.app.tinkro-theme:not(.display-mode-active)';
const tokens = declarations(':root');
const luminance = hex => {
  const rgb = hex.replace('#', '').match(/../g).map(v => parseInt(v, 16) / 255)
    .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
};
const contrast = (a, b) => {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + .05) / (values[1] + .05);
};

test('Tinkro brand palette and text contrast are explicit reusable tokens', () => {
  assert.equal(tokens['--brand-navy'], '#203065');
  assert.equal(tokens['--brand-blue'], '#417abe');
  assert.equal(tokens['--brand-teal'], '#16b9a6');
  for (const ink of ['--ink-primary', '--ink-secondary', '--ink-muted', '--brand-link']) {
    for (const surface of ['--surface-card', '--surface-canvas']) {
      assert.ok(contrast(tokens[ink], tokens[surface]) >= 4.5, `${ink} on ${surface}`);
    }
  }
  assert.ok(contrast(tokens['--brand-navy'], '#ffffff') >= 4.5);
});

test('large surfaces use warm paper rather than a blue social-feed shell or bright white', () => {
  assert.equal(tokens['--surface-canvas'], '#dedcd5');
  assert.equal(tokens['--surface-card'], '#eeeae1');
  assert.ok(luminance(tokens['--surface-canvas']) < .82);
  assert.ok(luminance(tokens['--surface-card']) < .90);
  assert.ok(luminance(tokens['--surface-card']) > luminance(tokens['--surface-canvas']));
  assert.ok(luminance(tokens['--surface-subtle']) < luminance(tokens['--surface-card']));
});

test('studio navigation and teal actions have contrast and do not add media transforms', () => {
  const shell = declarations(scope);
  assert.equal(declarations(`${scope} .header`).background, 'transparent');
  assert.equal(declarations(`${scope} .maker-nav`).background, 'var(--brand-navy)');
  assert.equal(shell['--primary-bg'], 'var(--brand-teal)');
  assert.ok(contrast(shell['--primary-ink'], tokens['--brand-teal']) >= 4.5);
  assert.ok(contrast(shell['--primary-ink'], tokens['--brand-action-hover']) >= 4.5);
  assert.ok(contrast(tokens['--studio-chalk'], tokens['--brand-navy']) >= 4.5);
  assert.match(declarations(scope)['background-image'], /radial-gradient/);
});

test('original blues are visibly used, not only declared in the palette', () => {
  assert.equal(declarations(`${scope} .brand-text`).background, 'var(--brand-navy)');
  assert.equal(tokens['--brand-link'], tokens['--brand-navy']);
  assert.equal(declarations(`${scope} .main :is(.maker-preview, .pi-deploy-panel, .debug-page-content)`)['border-top'], '3px solid var(--brand-blue)');
  assert.equal(declarations(`${scope} :is(.maker-eyebrow, .workflow-eyebrow)::before`).background, 'var(--brand-blue)');
  const nav = declarations(`${scope} .maker-nav`);
  assert.ok(contrast(nav['--text-faint'], tokens['--brand-navy']) >= 4.5);
  assert.ok(contrast(tokens['--studio-chalk'], nav['--control-hover']) >= 4.5);
});

test('new theme loads last and excludes optical HUD without rewriting camera geometry', () => {
  const main = read('../src/main.tsx');
  assert.ok(main.indexOf('./tinkro.css') > main.indexOf('./responsive.css'));
  css.walkRules(rule => {
    if (rule.selector === ':root' || rule.selector === '.brand-logo') return;
    assert.match(rule.selector, /\.tinkro-theme:not\(\.display-mode-active\)/);
  });
  css.walkDecls(d => assert.ok(!['transform', 'translate', 'scale'].includes(d.prop), d.prop));
  assert.equal(declarations(`${scope} :is(.video-shell, .circuit-viewport, .concept-canvas)`)['color-scheme'], 'dark');
});

test('public titles and accessible logo use Tinkro in both languages', () => {
  for (const language of ['en', 'zh-TW']) {
    const locale = JSON.parse(read(`../src/locales/${language}.json`));
    assert.equal(locale['app.title'], 'Tinkro');
    assert.doesNotMatch(JSON.stringify(locale), /Board ?Vision/);
  }
  assert.match(read('../index.html'), /<title>Tinkro<\/title>/);
  assert.match(read('../src/App.tsx'), /className="brand-logo"[^>]*alt=\{t\("app.title"\)\}/);
  const logo = readFileSync(new URL('../public/brand/tinkro-dark.png', import.meta.url));
  assert.equal(logo.subarray(1, 4).toString(), 'PNG');
  assert.equal(logo.readUInt32BE(16), 2048);
  assert.equal(logo.readUInt32BE(20), 1024);
  for (const color of ['#203065', '#417ABE', '#16B9A6']) {
    assert.ok(read('../public/brand/tinkro-symbol.svg').toUpperCase().includes(color.toUpperCase()));
  }
});

test('branding retains saved drafts, calibration keys and remote service identity', () => {
  assert.match(read('../src/lib/makerMigration.ts'), /boardvision\.maker\.v1/);
  assert.match(read('../src/components/VideoView.tsx'), /boardvision\.gpio-pin-calibration\.v1/);
  assert.match(read('../../backend/app/pi_deploy.py'), /SERVICE = "boardvision-pi\.service"/);
  assert.match(read('../src/lib/debugSessions.ts'), /boardvision\.ai-debug-session\.v1/);
});

test('light guide resets dark overlay variables and text shadow', () => {
  const guide = declarations(`${scope} .photo-guide.component-guide`);
  assert.equal(guide['--text-dim'], 'var(--ink-secondary)');
  assert.equal(guide['--border'], 'var(--line-default)');
  assert.equal(guide['text-shadow'], 'none');
  assert.equal(guide['backdrop-filter'], 'none');
});

test('base inputs use low specificity so code editors retain the dark surface', () => {
  assert.equal(declarations(`${scope} :where(input:not([type=checkbox]):not([type=radio]), textarea)`)['background-color'], 'var(--control-bg)');
  const code = declarations(`${scope} :is(.pi-code-editor, .pi-console, .debug-page pre, .component-test-card pre)`);
  assert.equal(code['color-scheme'], 'dark');
  assert.ok(contrast(code.color, code.background) >= 4.5);
});

test('primary action, semantic outcomes and keyboard focus remain distinguishable', () => {
  assert.equal(declarations(`${scope} :is(button, summary, select, input, textarea, a):focus-visible`).outline, '2px solid var(--accent)');
  assert.equal(declarations(`${scope} :is(.test-outcome.passed, .workflow-state.good)`).color, 'var(--ok)');
  assert.equal(declarations(`${scope} :is(.test-outcome.failed, .debug-check-feedback.is-error)`).color, 'var(--danger)');
  const variables = declarations(scope);
  for (const [status, surface] of [['--ok', '--surface-teal'], ['--warn', '--surface-warning'], ['--danger', '--surface-danger']]) {
    assert.ok(contrast(variables[status], tokens[surface]) >= 4.5, `${status} on ${surface}`);
    assert.ok(contrast(variables[status], tokens['--surface-card']) >= 4.5, `${status} on card`);
  }
});

test('isolated visual preview cannot proxy production or contact Pi/cloud', () => {
  const server = read('./tinkro-preview.mjs');
  assert.match(server, /connect-src 'none'/);
  assert.match(server, /startPreview\(port=18770\)/);
  assert.match(server, /server\.listen\(port,'127\.0\.0\.1'/);
  assert.match(server, /No API in this preview/);
  assert.match(read('./tinkro-preview.tsx'), /window.fetch=async\(\)=>\{throw Error/);
  assert.match(read('./tinkro-preview.tsx'), /window.WebSocket=class \{constructor\(\)\{throw Error/);
});
