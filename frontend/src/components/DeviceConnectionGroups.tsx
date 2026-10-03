import type { ReactNode } from "react";
import "../deviceConnections.css";

const phoneIcon = <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
  <rect x="5.5" y="2" width="9" height="16" rx="2" stroke="currentColor" strokeWidth="1.4" />
  <path d="M8 4h4M9 15.5h2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
</svg>;
const piIcon = <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
  <rect x="4" y="4" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.4" />
  <rect x="7" y="7" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.2" />
  <path d="M7 1.5V4m6-2.5V4M7 16v2.5m6-2.5v2.5M1.5 7H4m-2.5 6H4M16 7h2.5M16 13h2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
</svg>;

/** Presentation only. Keep each device's existing controller and portal host. */
export function DeviceConnectionGroups({ phone, pi, phoneLabel, piLabel, phoneName = phoneLabel, piName = piLabel }: {
  phone: ReactNode; pi: ReactNode; phoneLabel: string; piLabel: string; phoneName?: string; piName?: string;
}) {
  return <div className="maker-connection-controls maker-device-connections">
    <div className="maker-device-group is-phone" role="group" aria-label={phoneLabel} title={phoneLabel}>
      <span className="maker-device-label">{phoneIcon}<span>{phoneName}</span></span>
      {phone}
    </div>
    <div className="maker-device-group is-pi" role="group" aria-label={piLabel} title={piLabel}>
      <span className="maker-device-label">{piIcon}<span>{piName}</span></span>
      {pi}
    </div>
  </div>;
}
