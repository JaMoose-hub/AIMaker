import { toDisplay, type Letterbox } from "../lib/geometry";
import { useI18n } from "../lib/i18n";
import type { BodyRecognition } from "../lib/realtimeFrame";

const NAMES: Record<string, string> = {
  "raspberry-pi-5": "Raspberry Pi 5", "arduino-uno-q": "Arduino UNO Q",
  "hc-sr04": "HC-SR04", "mrd-tf240-8p-cs": "MRD-TF240-8P-CS",
};

/** Eye-only body labels; Webcam renders the original GPIO/Pin overlays instead. */
export function ObjectRecognitionOverlay({ items, letterbox, width, height }: {
  items: BodyRecognition[]; letterbox: Letterbox; width: number; height: number;
}) {
  const { t } = useI18n();
  if (!items.length) return null;
  return <svg className="object-recognition-overlay" width={width} height={height} role="presentation">
    {items.map(item => {
      const points = item.outline.map(([x, y]) => toDisplay(letterbox, x, y));
      const labelPoints = item.labelAnchorOutline?.map(([x, y]) => toDisplay(letterbox, x, y)) ?? points;
      const x = Math.max(8, Math.min(...labelPoints.map(point => point.x)));
      const y = Math.max(23, Math.min(...labelPoints.map(point => point.y)) - 8);
      const label = `${NAMES[item.id] ?? item.id}${item.pinsLocated ? "" : ` · ${t(item.clipped ? "camera.bodyClipped" : "camera.bodyPinsLocating")}`}`;
      return <g key={item.id} data-body-component={item.id} data-pins-located={item.pinsLocated}>
        {item.drawOutline && <polygon className="board-outline object-recognition-outline" points={points.map(point => `${point.x},${point.y}`).join(" ")} />}
        <text className="object-recognition-label" x={x} y={y}>{label}</text>
      </g>;
    })}
  </svg>;
}
