import { useEffect, useRef, useState } from "react";
import { useI18n } from "./i18n";
import { initialMaker, restoreMaker, type MakerState } from "./maker";
import { MAKER_STORAGE } from "./makerMigration";
import { testBindings, changedTestBindings, invalidateEditedBindings } from "./componentTests";

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
  const previousBindings = useRef(testBindings(state));
  useEffect(() => {
    const next = testBindings(state);
    const changed = changedTestBindings(previousBindings.current, next);
    previousBindings.current = next;
    // This observes actual edits in this tab across all maker stages, not passive
    // server results. Exact old keys prevent cancelling another tab's newer run.
    if (changed.length) void invalidateEditedBindings(changed).catch(() => {
      // Offline results stay visibly stale via their guide_key. Active run stop
      // controls and the server reservation are retained until reconnection.
    });
  }, [state.design, state.guide]);
  useEffect(() => {
    try { localStorage.setItem(STORAGE, JSON.stringify(state)); setSaved(true); } catch { setSaved(false); }
  }, [state]);
  return { state, setState, saved };
}
