import { useState } from 'react';
import { useMakerText } from '../lib/useMaker';
import { expectedWiringLocation, wiringTargetLabel } from '../lib/wiringExpectedLocation';
import type { WiringReviewResult } from '../lib/wiringReview';
import './wiringExpectedLocation.css';

/** A design locator only. Selection never changes the guide, a photo, or a confirmation. */
export function WiringExpectedLocation({ rows }: { rows: WiringReviewResult[] }) {
  const tr = useMakerText();
  const [choice, setChoice] = useState<string | null>(null);
  const targets = rows.flatMap(row => {
    const location = expectedWiringLocation(row);
    return location ? [{ row, location }] : [];
  });
  const selected = targets.find(target => target.row.wire_id === choice) ?? targets[0];
  if (!selected) return null;
  const { row, location } = selected;
  const rowLabel = location.row === 'inner' ? tr('內排・靠板中央', 'Inner row · toward board centre') : tr('外排・靠板邊緣', 'Outer row · toward board edge');
  const label = wiringTargetLabel(row, tr);
  return <section className="wiring-expected-location" aria-label={tr('設計應接位置', 'Designed connection position')} data-wire-id={row.wire_id}>
    <details className="wiring-expected-map"><summary>{tr('查看應接位置', 'View intended connection')}</summary>
    <div className="wiring-expected-body">
    <header><strong>{tr('設計應接位置', 'Designed connection')}</strong><span>{label}</span></header>
    {targets.length > 1 ? <div className="wiring-expected-tabs" role="group" aria-label={tr('查看這條線的應接位置', 'View the designed position for a wire')}>
      {targets.map(target => <button key={target.row.wire_id} type="button" aria-pressed={target.row.wire_id === row.wire_id}
        onClick={() => setChoice(target.row.wire_id)}>{wiringTargetLabel(target.row, tr)}</button>)}
    </div> : null}
    <p>{rowLabel} · {tr(`第 ${location.number} 個位置`, `position ${location.number}`)}</p>
    <svg viewBox="0 0 430 126" role="img" aria-label={tr(`${label}：${rowLabel}第 ${location.number} 個；從遠離 USB 與網路孔的一端數起。`, `${label}: ${rowLabel}, position ${location.number}; count from the end away from USB and Ethernet.`)}>
      <rect x="3" y="16" width="424" height="97" rx="8" fill="#274c40" stroke="#617f72" />
      <text x="170" y="31" textAnchor="middle" fontSize="10" fill="#e3f4ec">{tr('板中央 ↑', 'Board centre ↑')}</text>
      <text x="9" y="12" fontSize="10" fill="currentColor">{tr('從這端開始 →', 'Count from this end →')}</text>
      <path d="M46 17V37M42 33L46 38L50 33" fill="none" stroke="#ffdd80" strokeWidth="2" />
      <rect x="375" y="45" width="42" height="62" rx="4" fill="#aab4b0" stroke="#dce6e0" />
      <text x="396" y="66" textAnchor="middle" fontSize="10" fill="#203b30">USB</text>
      <text x="396" y="83" textAnchor="middle" fontSize="9" fill="#203b30">{tr('網路孔', 'Ethernet')}</text>
      <text x="18" y="61" textAnchor="middle" fontSize="10" fill="#eff9f2">{tr('內', 'IN')}</text>
      <text x="18" y="88" textAnchor="middle" fontSize="10" fill="#eff9f2">{tr('外', 'OUT')}</text>
      {Array.from({ length: 20 }, (_, index) => index + 1).map(number => <g key={number}>
        <text x={46 + (number - 1) * 16.6} y="43" textAnchor="middle" fontSize="8" fill="#d3e7dc">{number}</text>
        {(['inner', 'outer'] as const).map((pinRow, index) => {
          const active = location.row === pinRow && location.number === number;
          return <g key={pinRow} data-row={pinRow} data-row-position={number} data-designed-target={active || undefined}>
            <circle cx={46 + (number - 1) * 16.6} cy={58 + index * 27} r={active ? 7 : 4.5}
              fill={active ? '#ffdf85' : '#183229'} stroke={active ? '#fff3c2' : '#839e8f'} strokeWidth={active ? 2 : 1} />
            {active ? <circle cx={46 + (number - 1) * 16.6} cy={58 + index * 27} r="2.5" fill="#61470d" /> : null}
          </g>;
        })}
      </g>)}
      <path d="M7 113H369" stroke="#c6d8cc" strokeWidth="2" />
      <text x="171" y="108" textAnchor="middle" fontSize="10" fill="#e3f4ec">{tr('板邊緣 ↓', 'Board edge ↓')}</text>
      <text x="423" y="124" textAnchor="end" fontSize="9" fill="currentColor">{tr('俯視示意・不是實拍判定', 'Top view · design, not photo evidence')}</text>
    </svg>
    <details><summary>{tr('腳號與 GPIO', 'Pin and GPIO reference')}</summary><p>{row.expected.component_pin} → Pi Pin {row.expected.physical_pin}
      {row.expected.bcm != null ? ` · GPIO${row.expected.bcm}` : row.expected.board_pin ? ` · ${row.expected.board_pin}` : ''}</p>
      <small>{tr('此圖沿用本次紀錄的設計接法；照片觀察與人工確認分開記錄。', 'This diagram uses the saved designed connection. Photo observations and manual confirmation remain separate.')}</small>
    </details>
    </div></details>
  </section>;
}
