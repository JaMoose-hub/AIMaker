import { useMakerText } from '../lib/useMaker';
import { wiringPhotoRow, type WiringCapturePlan, type WiringPhotoRole } from '../lib/wiringReview';

/** A framing diagram, deliberately without pin numbers or wiring verdicts. */
export function WiringFramingGuide({ role, capturePlan, className = 'wiring-chat-framing-image' }: {
  role: WiringPhotoRole; capturePlan?: WiringCapturePlan; className?: string;
}) {
  const tr = useMakerText();
  const target = wiringPhotoRow(role, capturePlan);
  if (target) return <svg className={className} viewBox="0 0 300 114" role="img"
    aria-label={target === 'inner' ? tr('俯視取景示意：高亮靠板中央的內排，另一排靠板邊緣。不是 GPIO 腳位圖。', 'Top-view framing diagram: highlight the inner row toward the board centre. The other row is toward the board edge. Not a GPIO pin map.')
      : tr('俯視取景示意：高亮靠板邊緣的外排，另一排靠板中央。不是 GPIO 腳位圖。', 'Top-view framing diagram: highlight the outer row toward the board edge. The other row is toward the board centre. Not a GPIO pin map.')}>
    <rect x="8" y="4" width="284" height="98" rx="7" fill="#416552" />
    <text x="20" y="21" fontSize="10" fill="#f0faf4">{tr('板中央 ↑', 'Board centre ↑')}</text>
    {(['inner', 'outer'] as const).map((row, index) => <g key={row} opacity={target === row ? 1 : .65}>
      <rect x="15" y={30 + index * 32} width="174" height="27" rx="4" fill={target === row ? '#102d37' : '#233831'} stroke={target === row ? '#70ddff' : '#728b80'} strokeWidth={target === row ? 2.5 : 1} />
      {Array.from({ length: 10 }, (_, pin) => <rect key={pin} x={24 + pin * 16} y={38 + index * 32} width="8" height="10" rx="1" fill="#e6c47b" />)}
      <text x="200" y={48 + index * 32} fontSize="12" fontWeight={target === row ? 700 : 400} fill={target === row ? '#b8efff' : '#e9f0eb'}>
        {row === 'inner' ? tr('內排', 'Inner row') : tr('外排', 'Outer row')}{target === row ? tr(' ← 拍這排', ' ← photo') : ''}
      </text>
    </g>)}
    <path d="M12 102H288" stroke="#c6d8cc" strokeWidth="2" />
    <text x="20" y="97" fontSize="10" fill="#f0faf4">{tr('板邊緣 ↓', 'Board edge ↓')}</text>
    <text x="286" y="112" textAnchor="end" fontSize="9" fill="currentColor">{tr('俯視示意・非腳號圖', 'Top view · not a pin map')}</text>
  </svg>;
  return <svg className={className} viewBox="0 0 220 104" role="img" aria-label={tr('取景示意：排針、插接底部、接頭和線色一起入鏡，不是 GPIO 腳位圖。', 'Framing example: include the header, insertion points, connectors and wire colors. This is not a GPIO pin map.')}>
    <rect x="18" y="71" width="184" height="18" rx="4" fill="#527b68" /><rect x="40" y="61" width="139" height="12" fill="#35424b" />
    {[0, 1, 2, 3, 4, 5, 6, 7].map(n => <g key={n}><path d={`M${51 + n * 16} 62v-12`} stroke="#9caab2" strokeWidth="3" />
      {n < 5 ? <><rect x={47 + n * 16} y="32" width="10" height="25" rx="2" fill="#263444" />
        <path d={`M${52 + n * 16} 32v-18`} stroke={['#d56b62', '#dcb64c', '#739ab6', '#82976c', '#9b7ea6'][n]} strokeWidth="5" /></> : null}</g>)}
    <rect x="34" y="8" width="148" height="75" rx="8" fill="none" stroke="#407a9c" strokeWidth="2" strokeDasharray="5 4" />
    <text x="110" y="101" textAnchor="middle" fontSize="10" fill="currentColor">{role === 'component_header' ? tr('保留 pin 文字', 'Keep pin labels') : tr('保留板緣與插接底部', 'Keep board edge and insertion points')}</text>
  </svg>;
}
