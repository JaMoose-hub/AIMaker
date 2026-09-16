import type { CSSProperties } from "react";
import {
  capColorVar,
  capLabel,
  pinDisplayName,
  sortedCapabilities,
} from "../lib/capabilities";
import { useI18n } from "../lib/i18n";
import type { BoardProfile, Capability, Chip, Pin } from "../lib/types";

interface CapabilityCardProps {
  profile: BoardProfile | null;
  pin: Pin | null;
  backendDown: boolean;
}

export function CapabilityCard({ profile, pin, backendDown }: CapabilityCardProps) {
  const { t } = useI18n();

  if (!profile) {
    return (
      <div className="side-card">
        <div className="card-kicker">{t("card.title")}</div>
        <div className="card-empty">
          {backendDown ? `${t("backend.down")} · ${t("backend.retrying")}` : t("card.loading")}
        </div>
      </div>
    );
  }

  return (
    <div className="side-card">
      {pin ? <PinDetail profile={profile} pin={pin} /> : <BoardSummary profile={profile} />}
    </div>
  );
}

function chipLabel(part: string, chip: Chip): string {
  return chip.core ? `${part} · ${chip.core}` : part;
}

function BoardSummary({ profile }: { profile: BoardProfile }) {
  const { t, tx } = useI18n();
  const { board } = profile;
  return (
    <>
      <div className="card-kicker">{t("card.title")}</div>
      <h2 className="board-name">{tx(board.name)}</h2>
      <div className="board-vendor">
        {board.vendor}
        {board.revision ? ` · ${board.revision}` : ""}
      </div>
      <div className="badge-row">
        <span className="badge badge-voltage">{board.logic_voltage}V</span>
        <span className="badge">{board.form_factor}</span>
      </div>
      <dl className="fact-list">
        <div className="fact">
          <dt>{t("card.mcu")}</dt>
          <dd>{chipLabel(board.mcu.part, board.mcu)}</dd>
        </div>
        {board.mpu && (
          <div className="fact">
            <dt>{t("card.mpu")}</dt>
            <dd>{chipLabel(board.mpu.part, board.mpu)}</dd>
          </div>
        )}
        <div className="fact">
          <dt>{t("card.logic")}</dt>
          <dd>{board.logic_voltage}V</dd>
        </div>
        <div className="fact">
          <dt>{t("card.pins")}</dt>
          <dd>{profile.pins.length}</dd>
        </div>
      </dl>
      {!board.five_volt_tolerant && (
        <div className="warning-banner warning">
          <span className="warn-icon">⚠</span>
          <span>{t("card.not5vTolerant")}</span>
        </div>
      )}
      <div className="card-hint">{t("card.hint")}</div>
    </>
  );
}

function capabilityDetail(cap: Capability): string {
  const detail = cap.role ?? cap.rail ?? cap.channel ?? "";
  return detail ? detail.toUpperCase() : "";
}

function PinDetail({ profile, pin }: { profile: BoardProfile; pin: Pin }) {
  const { t, tx } = useI18n();
  const header = profile.headers.find((h) => h.id === pin.header);

  return (
    <>
      <div className="card-kicker">{header ? tx(header.name) : pin.header}</div>
      <div className="pin-title-row">
        <h2 className="pin-silkscreen">{pinDisplayName(pin)}</h2>
        <span className="pin-id">{pin.id} · Pin {pin.silkscreen}</span>
      </div>

      <div className="chip-row">
        {sortedCapabilities(pin).map((cap, index) => {
          const detail = capabilityDetail(cap);
          return (
            <span
              key={`${cap.type}-${index}`}
              className="chip"
              style={{ "--c": capColorVar(cap.type, pin, cap) } as CSSProperties}
              title={cap.note ? tx(cap.note) : undefined}
            >
              {capLabel(t, cap.type)}
              {detail ? ` ${detail}` : ""}
            </span>
          );
        })}
      </div>

      {pin.electrical && (
        <section className="card-section">
          <h3>{t("card.electrical")}</h3>
          <dl className="fact-list">
            <div className="fact">
              <dt>{t("card.voltage")}</dt>
              <dd>{pin.electrical.voltage}V</dd>
            </div>
            {pin.electrical.max_current_ma !== undefined && (
              <div className="fact">
                <dt>{t("card.maxCurrent")}</dt>
                <dd>{pin.electrical.max_current_ma} mA</dd>
              </div>
            )}
            {pin.electrical.five_volt_tolerant !== undefined && (
              <div className="fact">
                <dt>{t("card.fiveVoltTolerant")}</dt>
                <dd>
                  {pin.electrical.five_volt_tolerant
                    ? t("card.fiveVoltTolerantTrue")
                    : t("card.no")}
                </dd>
              </div>
            )}
          </dl>
        </section>
      )}

      <p className="pin-desc">{tx(pin.description)}</p>

      {pin.usage_examples && pin.usage_examples.length > 0 && (
        <section className="card-section">
          <h3>{t("card.usage")}</h3>
          <ul className="usage-list">
            {pin.usage_examples.map((usage, index) => (
              <li key={index}>{tx(usage)}</li>
            ))}
          </ul>
        </section>
      )}

      {pin.warnings?.map((warning, index) => (
        <div key={index} className={`warning-banner ${warning.severity}`}>
          {warning.severity !== "info" && <span className="warn-icon">⚠</span>}
          <span>{tx(warning.text)}</span>
        </div>
      ))}
    </>
  );
}
