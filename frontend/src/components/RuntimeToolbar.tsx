import { useEffect, useId, useRef } from "react";
import { useI18n } from "../lib/i18n";
import type { ControllerSummary, Locale } from "../lib/types";
import { ThemeSelect } from "./ThemeSelect";

interface RuntimeToolbarProps {
  collapsible?: boolean;
  controllers: ControllerSummary[];
  activeBoardId: string | null;
  busy: boolean;
  disabled: boolean;
  error: string | null;
  onControllerChange: (boardId: string) => void;
  onLocaleChange: (locale: Locale) => void;
}

export function RuntimeToolbar({
  collapsible = false,
  controllers,
  activeBoardId,
  busy,
  disabled,
  error,
  onControllerChange,
  onLocaleChange,
}: RuntimeToolbarProps) {
  const { locale, t, tx } = useI18n();
  const menu = useRef<HTMLDetailsElement>(null);
  const settingsId = useId();
  useEffect(() => {
    if (!collapsible) return;
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) {
        menu.current.open = false;
      }
    };
    document.addEventListener("pointerdown", closeOutside, true);
    return () => document.removeEventListener("pointerdown", closeOutside, true);
  }, [collapsible]);

  const controls = (
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
      <label className="runtime-select locale-select">
        <span>{t("runtime.languageLabel")}</span>
        <select
          value={locale}
          aria-label={t("runtime.languageAria")}
          onChange={(event) => onLocaleChange(event.target.value as Locale)}
        >
          <option value="zh-TW">{t("runtime.languageZh")}</option>
          <option value="en">English</option>
        </select>
      </label>
      <ThemeSelect />
    </div>
  );
  return <>
    {collapsible ? <details className="runtime-settings" ref={menu}
      onKeyDown={event => {
        if (event.key === "Escape" && menu.current?.open) {
          event.preventDefault();
          event.stopPropagation();
          menu.current.open = false;
          menu.current.querySelector("summary")?.focus();
        }
      }}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
      }}>
      <summary aria-controls={settingsId}><span aria-hidden="true">⚙</span>{t("runtime.settingsLabel")}</summary>
      <div className="runtime-settings-popover" id={settingsId}>{controls}</div>
    </details> : controls}
    {error ? <span className="runtime-error" role="status">{error}</span> : null}
  </>;
}
