import type { CSSProperties } from "react";
import { FILTER_COLOR_VAR, FILTERS, type FilterId } from "../lib/capabilities";
import { useI18n } from "../lib/i18n";

interface FilterBarProps {
  filter: FilterId;
  onChange: (filter: FilterId) => void;
}

/** Radio-style capability filter chips; clicking the active chip resets to "all". */
export function FilterBar({ filter, onChange }: FilterBarProps) {
  const { t } = useI18n();
  return (
    <div className="filter-bar" role="radiogroup" aria-label={t("card.capabilities")}>
      {FILTERS.map((id) => {
        const active = filter === id;
        const colorVar = id === "all" ? null : FILTER_COLOR_VAR[id];
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={active}
            className={`filter-chip${active ? " active" : ""}`}
            style={colorVar ? ({ "--c": `var(${colorVar})` } as CSSProperties) : undefined}
            onClick={() => onChange(active ? "all" : id)}
          >
            {colorVar && <span className="chip-dot" aria-hidden="true" />}
            {t(`filter.${id}`)}
          </button>
        );
      })}
    </div>
  );
}
