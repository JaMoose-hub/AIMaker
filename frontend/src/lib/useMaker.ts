import { useEffect, useState } from "react";
import { useI18n } from "./i18n";
import { initialMaker, restoreMaker, type MakerState } from "./maker";
import { MAKER_STORAGE } from "./makerMigration";

const STORAGE = MAKER_STORAGE;
export function useMakerText() {
  const { locale } = useI18n();
  return (zh: string, en: string): string => locale === "en" ? en : zh;
}
export function useMaker() {
  const [state, setState] = useState<MakerState>(() => {
    try { return restoreMaker(localStorage.getItem(STORAGE)); } catch { return initialMaker(); }
  });
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    try { localStorage.setItem(STORAGE, JSON.stringify(state)); setSaved(true); } catch { setSaved(false); }
  }, [state]);
  return { state, setState, saved };
}
