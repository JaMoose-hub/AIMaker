import { useI18n } from "../lib/i18n";
import type { ControllerSummary, Locale } from "../lib/types";

interface RuntimeToolbarProps {
  controllers: ControllerSummary[];
  activeBoardId: string | null;
  busy: boolean;
  disabled: boolean;
  error: string | null;
  onControllerChange: (boardId: string) => void;
  onLocaleChange: (locale: Locale) => void;
}

export function RuntimeToolbar({
  controllers,
  activeBoardId,
  busy,
  disabled,
  error,
  onControllerChange,
  onLocaleChange,
}: RuntimeToolbarProps) {
  const { locale, t, tx } = useI18n();
  const active = controllers.find((item) => item.board_id === activeBoardId);

  return (
    <div className="runtime-toolbar" aria-label={t("runtime.toolbarLabel")}>
      <label className="runtime-select">
        <span>{t("runtime.controllerLabel")}</span>
        <select
          value={activeBoardId ?? ""}
          disabled={disabled || busy || controllers.length === 0}
          aria-label={t("runtime.controllerAria")}
          onChange={(event) => onControllerChange(event.target.value)}
        >
          {controllers.map((controller) => (
            <option key={controller.board_id} value={controller.board_id}>
              {tx(controller.name)}
            </option>
          ))}
        </select>
      </label>
      <span
        className={`runtime-model-state${active?.model.fallback_active ? " fallback" : " ready"}`}
        title={
          active?.model.fallback_active
            ? t("runtime.modelFallbackTooltip")
            : t("runtime.modelReadyTooltip")
        }
      >
        {busy
          ? t("runtime.switching")
          : active?.model.fallback_active
            ? t("runtime.model4ptFallback")
            : active?.model.keypoint_count === 8
              ? t("runtime.model8pt")
              : t("runtime.model4pt")}
      </span>
      <label className="runtime-select locale-select">
        <span>{t("runtime.languageLabel")}</span>
        <select
          value={locale}
          aria-label={t("runtime.languageAria")}
          onChange={(event) => onLocaleChange(event.target.value as Locale)}
        >
          <option value="zh-TW">繁體中文</option>
          <option value="en">English</option>
        </select>
      </label>
      {error ? <span className="runtime-error" role="status">{error}</span> : null}
    </div>
  );
}
