import { useSyncExternalStore } from "react";
import { useI18n } from "../lib/i18n";
import { getTheme, setTheme, subscribeTheme, normalizeTheme } from "../lib/theme";

export function ThemeSelect() {
  const { t } = useI18n();
  const theme = useSyncExternalStore(subscribeTheme, getTheme, () => "dark");
  return <label className="runtime-select theme-select">
    <span>{t("runtime.themeLabel")}</span>
    <select value={theme} aria-label={t("runtime.themeLabel")} onChange={event => setTheme(normalizeTheme(event.target.value))}>
      <option value="dark">{t("runtime.themeDark")}</option>
      <option value="light">{t("runtime.themeLight")}</option>
    </select>
  </label>;
}
