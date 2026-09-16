import type { GuidedComponentId } from "../lib/componentWiringGuides";
import { MODULE_WIDTH } from "../lib/circuitLayout";

/** Recognisable schematic silhouettes, not exact PCB dimensions or live readings. */
export function CircuitModuleArt({ id, x, y, height }: { id: GuidedComponentId; x: number; y: number; height: number }) {
  const width = MODULE_WIDTH;
  const tft = id === "mrd-tf240-8p-cs";
  return <g transform={`translate(${x} ${y})`} aria-hidden="true" pointerEvents="none">
    <rect width={width} height={height} rx="9" fill={tft ? "#702e3f" : "#185568"} stroke={tft ? "#cd738a" : "#52a1b1"} strokeWidth="2" />
    {[[12, 12], [width - 12, 12], [12, height - 12], [width - 12, height - 12]].map(([cx, cy], i) =>
      <g key={i}><circle cx={cx} cy={cy} r="6" fill="#b6a875" /><circle cx={cx} cy={cy} r="3" fill="#0d1723" /></g>)}
    {id === "hc-sr04" ? <>
      {[86, width - 86].map(cx => <g key={cx}>
        <circle cx={cx} cy="57" r="45" fill="#8b9da9" stroke="#d2dde3" strokeWidth="3" />
        <circle cx={cx} cy="57" r="37" fill="#293c4a" stroke="#536e7e" strokeWidth="2" />
        <circle cx={cx} cy="57" r="31" fill="#132634" />
        {[-20, -10, 0, 10, 20].map(offset => <path key={offset} d={`M ${cx - 24} ${57 + offset} h 48 M ${cx + offset} 33 v 48`} stroke="#354c5d" strokeWidth="2" />)}
      </g>)}
      <rect x="156" y="48" width="40" height="22" rx="3" fill="#142730" stroke="#7f9395" />
      <text x={width / 2} y="27" textAnchor="middle" fill="#c4e6e7" fontSize="13">HC-SR04</text>
    </> : <>
      <rect x="30" y="36" width={width - 60} height={height - 52} rx="5" fill="#b6b9bf" />
      <rect x="37" y="43" width={width - 74} height={height - 66} rx="3" fill="#08121e" stroke="#2b404f" strokeWidth="2" />
      <path d={`M 48 53 H ${width - 68} L 48 ${height - 40} Z`} fill="#112534" />
      <rect x="72" y="77" width="45" height="32" rx="3" fill="none" stroke="#4b8a97" strokeWidth="2" />
      <path d="M 80 119 h 28 M 94 109 v 10" stroke="#4b8a97" strokeWidth="2" />
      <text x="138" y="93" fill="#8ba4b5" fontSize="19">2.4″ TFT</text>
      <text x="138" y="116" fill="#758a9a" fontSize="12">DISPLAY OFF</text>
    </>}
  </g>;
}
