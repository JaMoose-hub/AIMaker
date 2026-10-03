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
  /** Hosts the existing VideoView-owned tools without remounting the camera. */
  cameraToolsRef?: (host: HTMLDivElement | null) => void;
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
  cameraToolsRef,
  onControllerChange,
  onLocaleChange,
}: RuntimeToolbarProps) {
  const { locale, t, tx } = useI18n();
  const menu = useRef<HTMLDetailsElement>(null);
  const settingsId = useId();
  useEffect(() => {
    if (!collapsible) return;
    const settings = menu.current;
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) {
        menu.current.open = false;
      }
    };
    // Native containment also includes VideoView controls portalled into Settings.
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || !settings?.open) return;
      event.preventDefault();
      event.stopPropagation();
      settings.open = false;
      settings.querySelector("summary")?.focus();
    };
    const closeOnBlur = (event: FocusEvent) => {
      if (settings && !(event.relatedTarget instanceof Node && settings.contains(event.relatedTarget))) settings.open = false;
    };
    document.addEventListener("pointerdown", closeOutside, true);
    settings?.addEventListener("keydown", closeOnEscape);
    settings?.addEventListener("focusout", closeOnBlur);
    return () => {
      document.removeEventListener("pointerdown", closeOutside, true);
      settings?.removeEventListener("keydown", closeOnEscape);
      settings?.removeEventListener("focusout", closeOnBlur);
    };
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
    {collapsible ? <details className="runtime-settings" ref={menu}>
      <summary aria-controls={settingsId}><span aria-hidden="true">⚙</span>{t("runtime.settingsLabel")}</summary>
      <div className="runtime-settings-popover" id={settingsId}>{controls}
        {cameraToolsRef ? <div className="camera-settings-slot" ref={cameraToolsRef} /> : null}
      </div>
    </details> : controls}
    {error ? <span className="runtime-error" role="status">{error}</span> : null}
  </>;
}
