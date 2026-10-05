import { createContext, useCallback, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

type HeaderPanel = "phone" | "pi" | "settings" | "reset";
type PanelState = HeaderPanel | null;
const HeaderPanels = createContext<{ active: PanelState; setActive: Dispatch<SetStateAction<PanelState>>;
  phoneUploadRequest: number; phoneUploadScope: string | null; openPhoneUpload: (scope?: string) => void; clearPhoneUpload: () => void } | null>(null);

/** One owner for header panels, including the phone panel's React portal. */
export function HeaderPanelProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<PanelState>(null);
  const [phoneUploadRequest, setPhoneUploadRequest] = useState(0);
  const [phoneUploadScope, setPhoneUploadScope] = useState<string | null>(null);
  const openPhoneUpload = useCallback((scope?: string) => { setActive('phone'); setPhoneUploadScope(scope ?? null); setPhoneUploadRequest(value => value + 1); }, []);
  const clearPhoneUpload = useCallback(() => setPhoneUploadScope(null), []);
  const value = useMemo(() => ({ active, setActive, phoneUploadRequest, phoneUploadScope, openPhoneUpload, clearPhoneUpload }), [active, phoneUploadRequest, phoneUploadScope, openPhoneUpload, clearPhoneUpload]);
  return <HeaderPanels.Provider value={value}>{children}</HeaderPanels.Provider>;
}

/** Reuse the existing QR/pairing panel; do not create a second mobile session. */
export function usePhoneUploadEntry() {
  const shared = useContext(HeaderPanels);
  return { request: shared?.phoneUploadRequest ?? 0, scope: shared?.phoneUploadScope ?? null, open: shared?.openPhoneUpload, clear: shared?.clearPhoneUpload };
}

export function useHeaderPanel(panel: HeaderPanel, initiallyOpen = false) {
  const shared = useContext(HeaderPanels);
  // Retain standalone controls outside the desktop workspace.
  const [localOpen, setLocalOpen] = useState(initiallyOpen);
  const setActive = shared?.setActive;
  const setOpen = useCallback((open: boolean) => {
    if (setActive) {
      // A late close/toggle from the previous panel must not close its successor.
      setActive(active => open ? panel : active === panel ? null : active);
    } else setLocalOpen(open);
  }, [panel, setActive]);
  return [shared ? shared.active === panel : localOpen, setOpen] as const;
}
