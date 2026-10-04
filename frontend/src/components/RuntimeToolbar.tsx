import { useEffect, useId, useRef } from "react";
import { useI18n } from "../lib/i18n";
import { useHeaderPanel } from "../lib/headerPanels";
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
  const [settingsOpen, setSettingsOpen] = useHeaderPanel("settings");
  const settingsId = useId();
  useEffect(() => {
    if (!collapsible) return;
    const settings = menu.current;
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) {
        setSettingsOpen(false);
      }
    };
    // Native containment also includes VideoView controls portalled into Settings.
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || !settings?.open) return;
      event.preventDefault();
      event.stopPropagation();
      setSettingsOpen(false);
      settings.querySelector("summary")?.focus();
    };
    const closeOnFocus = (event: FocusEvent) => {
      if (settings?.open && event.target instanceof Node && !settings.contains(event.target)) setSettingsOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside, true);
    settings?.addEventListener("keydown", closeOnEscape);
    document.addEventListener("focusin", closeOnFocus);
    return () => {
      document.removeEventListener("pointerdown", closeOutside, true);
      settings?.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("focusin", closeOnFocus);
    };
  }, [collapsible, setSettingsOpen]);

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
    {collapsible ? <details className="runtime-settings" ref={menu} open={settingsOpen}>
      <summary aria-controls={settingsId} aria-label={t("runtime.settingsLabel")} title={t("runtime.settingsLabel")}
        aria-expanded={settingsOpen}
        onClick={event => { event.preventDefault(); setSettingsOpen(!settingsOpen); }}>
        <svg className="runtime-settings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
          <path d="m9.5 3-.5 2a7 7 0 0 0-1.6.9l-2-.6-2.5 4.3 1.5 1.4a8 8 0 0 0 0 1.8L2.9 14l2.5 4.3 2-.6a7 7 0 0 0 1.6.9l.5 2h5l.5-2a7 7 0 0 0 1.6-.9l2 .6 2.5-4.3-1.5-1.4a8 8 0 0 0 0-1.8l1.5-1.4-2.5-4.3-2 .6A7 7 0 0 0 15 5l-.5-2Z" />
          <circle cx="12" cy="12" r="3" />
        </svg><span className="runtime-settings-label">{t("runtime.settingsLabel")}</span>
      </summary>
      <div className="runtime-settings-popover" id={settingsId}>{controls}
        {cameraToolsRef ? <div className="camera-settings-slot" ref={cameraToolsRef} /> : null}
      </div>
    </details> : controls}
    {error ? <span className="runtime-error" role="status">{error}</span> : null}
  </>;
}
