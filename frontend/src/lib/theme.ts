/** Display preference only: never subscribes to or mutates Maker/Pi state. */
export type Theme = "dark" | "light";
export const THEME_STORAGE_KEY = "boardvision.theme.v1";
const THEME_EVENT = "tinkro:theme-change";
export const normalizeTheme = (value: unknown): Theme => value === "light" ? "light" : "dark";

export function getTheme(): Theme {
  return typeof document === "undefined" ? "dark" : normalizeTheme(document.documentElement.dataset.theme);
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f3f4f7" : "#0a0b10");
}

export function setTheme(value: Theme) {
  const theme = normalizeTheme(value);
  applyTheme(theme);
  try { window.localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* Session-only preference. */ }
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function subscribeTheme(notify: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    applyTheme(normalizeTheme(event.newValue));
    notify();
  };
  window.addEventListener(THEME_EVENT, notify);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(THEME_EVENT, notify);
    window.removeEventListener("storage", onStorage);
  };
}
