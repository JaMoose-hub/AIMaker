// Local-only visual regression gallery. All observations are explicitly test fixtures.
// Run: node tools/cloud_wiring_preview.mjs, then open http://127.0.0.1:8111/
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { renderDetails, resultFixture } from './cloud_wiring_fixture.mjs';

const states = ['uncertain', 'suspected_issue', 'looks_matched', 'needs_review', 'stale', 'busy', 'error', 'connectors', 'empty'];
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const photo = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><rect width="400" height="240" fill="#233849"/><text x="50" y="120" fill="white" font-size="24">TEST FIXTURE ONLY</text></svg>');
createServer(async (req, res) => {
  if (req.url === '/styles.css') {res.writeHead(200, {'Content-Type': 'text/css'}); res.end(styles); return;}
  try {
    const url = new URL(req.url, 'http://127.0.0.1:8111');
    const locale = url.searchParams.get('lang') === 'en' ? 'en' : 'zh-TW';
    const state = states.includes(url.searchParams.get('state')) ? url.searchParams.get('state') : 'uncertain';
    const zh = locale === 'zh-TW';
    const result = structuredClone(resultFixture);
    result.verdict = states.slice(0, 4).includes(state) ? state : 'looks_matched';
    result.summary = zh ? 'Pi 端可見橘色線，感測器端可見棕色線；中間路徑部分重疊，尚無法確認是否為同一條線。'
      : 'Orange insulation is visible at the Pi and brown at the sensor. The middle routes overlap, so the same wire cannot yet be confirmed.';
    if (state === 'looks_matched') result.summary = zh ? '照片中兩端位於目標腳位，且可以沿著線路辨認為同一條線。' : 'Both ends appear at the target pins and the route can be followed between them.';
    if (state === 'suspected_issue') {result.board_endpoint.state = 'other'; result.summary = zh ? 'Pi 端疑似插在相鄰的腳位，請與本步目標 Pin 6 比對。' : 'The Pi connector appears to be on an adjacent pin; compare it with target Pin 6.';}
    result.board_endpoint.evidence = zh ? 'pi_pins 可見黑色插接端子，但底部遮住腳位邊界，無法確認是否插在指定的 Pin 6。' : 'pi_pins shows the black connector, but its base obscures the boundary of Pin 6.';
    result.component_endpoint.evidence = zh ? 'component_pins 可見 GND 位置的端子與棕色線皮。' : 'component_pins shows a connector and brown insulation at GND.';
    result.wire_colors.board.name = 'orange'; result.wire_colors.component.name = 'brown';
    result.wire_colors.board.evidence = zh ? '測試資料：Pi 端可見橘色線皮。' : 'Fixture: orange insulation at the Pi.';
    result.wire_colors.component.evidence = zh ? '測試資料：零件端可見棕色線皮。' : 'Fixture: brown insulation at the module.';
    result.wire_colors.comparison = 'different';
    result.wire_colors.evidence = zh ? '兩端顏色不同；仍須連同腳位與完整線路一起判讀。' : 'Colors differ; pin identity and the full route must also be considered.';
    result.wire_path.evidence = zh ? 'pi_overview 的中段線路重疊，無法分辨每条線各自通往哪一端。' : 'The middle routes overlap in pi_overview, making wire identity ambiguous.';
    if (['looks_matched', 'needs_review', 'stale', 'busy', 'error'].includes(state)) {
      result.board_endpoint.state = 'target'; result.board_endpoint.observed_pin = 'GND_P6';
      result.same_wire = 'consistent'; result.wire_path.visibility = 'traceable';
      result.wire_colors.board.name = 'brown'; result.wire_colors.comparison = 'similar';
      result.board_endpoint.evidence = zh ? '測試資料：目標腳位與端子底部可辨識。' : 'Fixture: the target pin and connector base are visible.';
      result.wire_colors.board.evidence = result.wire_colors.component.evidence;
      result.wire_colors.evidence = zh ? '測試資料：兩端可見棕色線皮。' : 'Fixture: brown insulation at both ends.';
      result.wire_path.evidence = zh ? '測試資料：全景中可追蹤兩端之間的路徑。' : 'Fixture: the route is traceable between both ends.';
      result.summary = zh ? '測試資料：照片外觀可辨識兩端及完整路徑。' : 'Fixture: both ends and the full path are visible.';
    }
    if (state === 'connectors' || state === 'empty') {
      result.verdict = state === 'empty' ? 'suspected_issue' : 'uncertain';
      result.board_endpoint = {state: state === 'empty' ? 'empty' : 'uncertain', observed_pin: null, evidence: 'Fixture: target identity unresolved'};
      result.wire_colors.board = {name: 'unknown', visibility: 'not_visible', evidence: 'Fixture: target not associated'};
      result.wire_colors.component = {name: 'brown', visibility: 'clear', evidence: 'Fixture: visible insulation'};
      result.wire_colors.comparison = 'uncertain';
      result.wire_colors.evidence = 'Fixture: target association remains unconfirmed';
      result.summary = 'Fixture: brown candidate connector visible; exact Pi pin remains unresolved';
      const observation = {target_identity: 'uncertain', target_pin_tip: 'not_visible', target_connector_id: null, evidence: 'Fixture: target pin not identified', connectors: [
        {id: 'a', position: 'Fixture A', contact: 'covers_pin', wire_color: {name: 'brown', visibility: 'clear', evidence: 'Fixture: rear insulation'}, evidence: 'Fixture: housing covers tip, not flush with PCB'},
        {id: 'b', position: 'Fixture B', contact: 'detached', wire_color: {name: 'orange', visibility: 'clear', evidence: 'Fixture: rear insulation'}, evidence: 'Fixture: gap beyond pin tip'},
      ]};
      result.visual_observations = {board: observation, component: observation};
    }
    const job = {status: 'completed', model: 'FIXTURE — no cloud call', result,
      capture: {captured_at: '2026-09-09T05:49:43Z', same_frame: true, mode: 'pin_crops'},
      images: ['pi_overview', 'pi_pins', 'component_pins'].map(name => ({name, url: photo}))};
    const card = await renderDetails(result, locale, {job, stale: state === 'stale', busy: state === 'busy',
      ...(state === 'needs_review' ? {target: {componentId: 'hc-sr04', componentPin: 'ECHO', boardLabel: 'Pin 12 · GPIO18'}} : {}),
      error: state === 'error' ? 'FIXTURE: Cloud unavailable. No real request was sent.' : null,
      onCheck: () => {}, checkDisabled: true, checkHint: 'Preview only — no cloud request'});
    res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'});
    res.end(`<!doctype html><html lang="${locale}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloud check — UI test fixtures</title><link rel="stylesheet" href="/styles.css"><style>body{display:block;overflow:auto;margin:0;background:#090e15;font-family:system-ui,sans-serif}main{max-width:720px;margin:24px auto;padding:16px}nav{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px}a{color:#9adfce}.fixture-note{color:#ffd08a;margin:0 0 18px;line-height:1.7}h1{font-size:18px;margin:0 0 14px;color:white}</style><main><h1>UI TEST FIXTURES · 非實拍判讀</h1><p class="fixture-note">版型測試資料，不代表您的接線。按鈕不會呼叫雲端。</p><nav>${states.map(s => `<a href="?state=${s}&lang=${locale}">${s}</a>`).join('')}<a href="?state=${state}&lang=${zh ? 'en' : 'zh-TW'}">${zh ? 'English' : '繁體中文'}</a></nav>${card}</main></html>`);
  } catch (error) {res.writeHead(500); res.end(String(error));}
}).listen(8111, '127.0.0.1', () => console.log('UI fixtures only: http://127.0.0.1:8111/'));
