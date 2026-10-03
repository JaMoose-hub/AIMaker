import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import postcss from 'postcss';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../src/tinkro.css'));
const declarations = selector => {
  const values = {};
  css.walkRules(selector, rule => rule.walkDecls(d => { values[d.prop] = d.value; }));
  return values;
};
const scope = '.app.tinkro-theme:not(.display-mode-active)';
const dark = declarations(':root'), light = {...dark,...declarations(':root[data-theme="light"]')};
const rgb = hex => hex.replace('#','').match(/../g).map(v=>parseInt(v,16));
const luminance = c => c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
const contrast = (a,b) => {const l=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (l[0]+.05)/(l[1]+.05)};
const paint = (value,base) => {
  if(value.startsWith('#'))return rgb(value);
  const [r,g,b,alpha] = value.match(/[\d.]+/g).map(Number);
  return [r,g,b].map((v,i)=>v*alpha/100+base[i]*(1-alpha/100));
};

test('Style 23 defines exact dark/light surfaces, brand colors and small radii',()=>{
  assert.equal(dark['--surface-canvas'],'#0a0b10');
  assert.equal(dark['--surface-card'],'#12141b');
  assert.equal(light['--surface-canvas'],'#f3f4f7');
  assert.equal(light['--surface-card'],'#ffffff');
  for(const tokens of [dark,light]){
    assert.equal(tokens['--brand-navy'],'#203065');
    assert.equal(tokens['--brand-blue'],'#417abe');
    assert.equal(tokens['--brand-teal'],'#16b9a6');
    assert.equal(tokens['--radius-card'],'8px');
    assert.equal(tokens['--radius-control'],'6px');
    assert.equal(tokens['--radius-tag'],'4px');
  }
  assert.doesNotMatch(css.toString(),/#dedcd5|#eeeae1|background-image: radial-gradient|border-top: 3px/);
});

for(const [theme,tokens] of [['dark',dark],['light',light]]){
  test(theme+' text, status chips, tonal and diff colors meet 4.5:1 on composited backgrounds',()=>{
    const panel=rgb(tokens['--surface-card']);
    for(const ink of ['--ink-primary','--ink-secondary','--ink-muted','--brand-link']){
      for(const surface of ['--surface-card','--surface-canvas','--surface-subtle']){
        assert.ok(contrast(rgb(tokens[ink]),rgb(tokens[surface]))>=4.5,theme+ink+surface);
      }
    }
    for(const [ink,bg] of [['--status-ok','--surface-teal'],['--status-warn','--surface-warning'],['--status-danger','--surface-danger'],['--brand-link','--surface-blue']]){
      assert.ok(contrast(rgb(tokens[ink]),paint(tokens[bg],panel))>=4.5,theme+ink);
    }
    const evidence=paint(tokens['--surface-evidence'],panel);
    assert.ok(contrast(rgb(tokens['--tonal-ink']),paint(tokens['--tonal-bg'],evidence))>=4.5);
    const diff=rgb(tokens['--diff-bg']);
    assert.ok(contrast(rgb(tokens['--diff-add-ink']),paint(tokens['--diff-add-bg'],diff))>=4.5);
    assert.ok(contrast(rgb(tokens['--status-danger']),paint(tokens['--diff-del-bg'],diff))>=4.5);
    assert.ok(contrast(rgb('#04241f'),rgb(tokens['--brand-teal']))>=4.5);
    assert.ok(contrast(rgb('#04241f'),rgb(tokens['--brand-action-hover']))>=4.5);
  });
}

test('theme paints load last but never transform camera geometry or change electrical tokens',()=>{
  const main=read('../src/main.tsx');
  assert.ok(main.indexOf('./tinkro.css')>main.indexOf('./guideAi.css'));
  css.walkDecls(d=>assert.ok(!['transform','translate','scale'].includes(d.prop),d.prop));
  assert.doesNotMatch(css.toString(),/--cap-|--wire-/);
  assert.equal(declarations(scope+' :is(.video-shell, .circuit-viewport, .concept-canvas)')['color-scheme'],'dark');
  assert.equal(declarations(scope+' .ai-debug-panel .ai-photo-card img')['color-scheme'],'dark');
  assert.equal(declarations('.app.display-mode-active')['color-scheme'],'dark');
  assert.equal(declarations('html:has(.display-mode-active)').background,'var(--bg)');
  const code=declarations(scope+' :is(.pi-code-editor, .pi-console, .debug-page pre, .component-test-card pre)');
  assert.equal(code['color-scheme'],'dark');
  assert.ok(contrast(rgb(code.color),rgb(code.background))>=4.5);
});

test('only the brand and prompt use aurora blur, with independent keyboard focus and reduced motion',()=>{
  css.walkDecls('filter',d=>{
    if(d.value.startsWith('blur('))assert.match(d.parent.selector,/brand-text::before|compose-row\)::before/);
    else if(d.value!=='none')assert.equal(d.parent.selector,':root[data-theme="light"] '+scope+' .brand-logo');
  });
  assert.equal(declarations(scope+' :is(button, summary, select, input, textarea, a):focus-visible').outline,'2px solid var(--accent)');
  assert.equal(declarations(scope+' :is(.maker-compose-row,.ai-debug-compose-row):focus-within').outline,'2px solid var(--brand-link)');
  assert.match(css.toString(),/@media \(prefers-reduced-motion: reduce\)/);
  assert.equal(declarations(scope+' .ws-dot')['box-shadow'],'none');
  assert.equal(declarations(scope+' .camera-tools-popover .status-metrics > .pill')['flex-basis'],'auto');
});

test('branding retains accessible title, saved drafts, calibration and remote service identity',()=>{
  for(const locale of ['en','zh-TW'])assert.equal(JSON.parse(read('../src/locales/'+locale+'.json'))['app.title'],'Tinkro');
  assert.match(read('../src/App.tsx'),/brand-title[^]*?t\("app.title"\)/);
  assert.match(read('../src/App.tsx'),/brand-logo[^>]*src="\/brand\/tinkro-dark\.png"[^>]*alt=\{t\("app.title"\)\}/);
  assert.match(read('../src/lib/makerMigration.ts'),/boardvision\.maker\.v1/);
  assert.match(read('../src/components/VideoView.tsx'),/boardvision\.gpio-pin-calibration\.v1/);
  assert.match(read('../../backend/app/pi_deploy.py'),/SERVICE = "boardvision-pi\.service"/);
  assert.match(read('../src/lib/debugSessions.ts'),/boardvision\.ai-debug-session\.v1/);
  assert.doesNotMatch(read('../src/lib/theme.ts'),/fetch\(|WebSocket|reload\(|maker\.v1|ai-debug-session/);
});

test('original supplied wordmark is unmodified, keeps its tagline and stays legible in light mode',()=>{
  const image=readFileSync(new URL('../public/brand/tinkro-dark.png',import.meta.url));
  assert.equal(createHash('sha256').update(image).digest('hex'),'8f1e0d78ea6bd5f278ce34309c17906f7ffb7b906c351c2b80e0940b43f59345');
  const app=read('../src/App.tsx');
  assert.match(app,/brand-subtitle">Vibe Maker Studio/);
  assert.doesNotMatch(app,/src="\/brand\/tinkro-symbol.svg"/);
  assert.match(read('./tinkro-preview.tsx'),/brand-logo[^>]*src="\/brand\/tinkro-dark\.png"[^>]*alt="Tinkro"/);
  assert.equal(declarations(':root[data-theme="light"] '+scope+' .brand-title').background,'transparent');
  assert.equal(declarations(':root[data-theme="light"] '+scope+' .brand-logo').filter,'url("/brand/tinkro-light-filter.svg#wordmark-ink")');
  assert.equal(declarations(scope+' .brand-logo').filter,undefined,'dark mode retains the original artwork');
  const filter=read('../public/brand/tinkro-light-filter.svg');
  assert.match(filter,/color-interpolation-filters="sRGB"/);
  const matrix=filter.match(/values="([\s\S]*?)"/)[1].trim().split(/\s+/).map(Number);
  const apply=rgba=>[0,1,2,3].map(row=>Math.min(1,Math.max(0,matrix.slice(row*5,row*5+4).reduce((sum,v,i)=>sum+v*rgba[i],matrix[row*5+4]))));
  assert.deepEqual(apply([1,1,1,1]).slice(0,3).map(v=>Math.round(v*255)),[16,19,28]);
  for(const color of [[0,.47,1,1],[0,.75,.65,1],[0,.47,1,.3],[0,0,0,0]])assert.deepEqual(apply(color),color,'brand colors and transparency survive');
  const wordmark=declarations(scope+' .brand-logo');
  assert.equal(wordmark.width,'128px');
  assert.equal(wordmark.height,'40px');
  assert.equal(wordmark['object-fit'],'cover');
  assert.equal(wordmark['object-position'],'center 44%');
  const compactWordmark=declarations(scope+' .maker-header-main .brand-logo');
  assert.equal(compactWordmark.width,'112px');
  assert.equal(compactWordmark.height,'35px');
});

test('proposal presentation preserves raw diff text and the existing explicit confirmation path',()=>{
  const debug=read('../src/components/DebugPage.tsx');
  assert.match(debug,/data-proposal=\{!record.candidate.applied\}/);
  assert.ok(debug.includes('record.candidate.diff.split(/(?<=\\n)/)'));
  assert.match(debug,/onClick=\{\(\)=>setConfirmAction\("apply"\)\}/);
  assert.match(debug,/action:"apply",context,candidate_id:record.candidate.id,confirmed:true/);
  assert.match(read('../src/components/DesignStudio.tsx'),/data-proposal=\{Boolean\(state.candidate\)\}/);
  assert.equal(declarations(scope+' .main .maker-preview[data-proposal="true"]').border,'1px dashed var(--border-strong)');
});

test('isolated preview cannot contact Pi, cloud or production storage',()=>{
  const server=read('./tinkro-preview.mjs');
  assert.match(server,/connect-src 'none'/);
  assert.match(server,/startPreview\(port=18770\)/);
  assert.match(server,/server\.listen\(port,'127\.0\.0\.1'/);
  assert.match(read('./tinkro-preview.tsx'),/window.fetch=async\(\)=>\{throw Error/);
  assert.match(read('./tinkro-preview.tsx'),/window.WebSocket=class \{constructor\(\)\{throw Error/);
});
