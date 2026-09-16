import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import zhTW from "../locales/zh-TW.json";
import en from "../locales/en.json";
import type { I18nText, Locale } from "./types";

/** Tiny i18n: `t(key)` for UI strings, `tx(obj)` for profile I18nText objects. */

const DEFAULT_LOCALE: Locale = "zh-TW";
const LOCALE_STORAGE_KEY = "boardvision.locale.v1";
const MESSAGES: Record<string, Record<string, string>> = { "zh-TW": zhTW, en };

function supportedLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  const normalized = value.toLowerCase();
  if (normalized.startsWith("zh")) return "zh-TW";
  if (normalized.startsWith("en")) return "en";
  return null;
}

function initialLocale(): { locale: Locale; preferred: boolean } {
  if (typeof window === "undefined") return { locale: DEFAULT_LOCALE, preferred: false };
  try {
    const stored = supportedLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
    if (stored) return { locale: stored, preferred: true };
  } catch {
    // Browser preference remains available when storage is blocked.
  }
  const browserLocale = supportedLocale(window.navigator.languages?.[0] ?? window.navigator.language);
  return browserLocale
    ? { locale: browserLocale, preferred: true }
    : { locale: DEFAULT_LOCALE, preferred: false };
}

export interface I18nApi {
  locale: Locale;
  setLocale: (locale: string) => void;
  applyDefaultLocale: (locale: string) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
  tx: (text: I18nText | undefined) => string;
}

const I18nContext = createContext<I18nApi | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(initialLocale, []);
  const [locale, setLocaleState] = useState<Locale>(initial.locale);
  const hasPreference = useRef(initial.preferred);

  const setLocale = useCallback((next: string) => {
    const selected = supportedLocale(next) ?? DEFAULT_LOCALE;
    hasPreference.current = true;
    setLocaleState(selected);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, selected);
    } catch {
      // The language still changes for this session.
    }
  }, []);

  const applyDefaultLocale = useCallback((next: string) => {
    if (hasPreference.current) return;
    setLocaleState(supportedLocale(next) ?? DEFAULT_LOCALE);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      let text = MESSAGES[locale]?.[key] ?? MESSAGES[DEFAULT_LOCALE]?.[key] ?? key;
      if (params) {
        for (const [name, value] of Object.entries(params)) {
          text = text.replace(`{${name}}`, String(value));
        }
      }
      return text;
    },
    [locale],
  );

  const tx = useCallback(
    (text: I18nText | undefined): string => {
      if (!text) return "";
      return text[locale]
        ?? text[DEFAULT_LOCALE]
        ?? text.en
        ?? Object.values(text)[0]
        ?? "";
    },
    [locale],
  );

  const value = useMemo<I18nApi>(
    () => ({ locale, setLocale, applyDefaultLocale, t, tx }),
    [locale, setLocale, applyDefaultLocale, t, tx],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nApi {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside <LocaleProvider>");
  return context;
}
