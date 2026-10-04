import { createContext, useCallback, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

type HeaderPanel = "phone" | "pi" | "settings";
type PanelState = HeaderPanel | null;
const HeaderPanels = createContext<{ active: PanelState; setActive: Dispatch<SetStateAction<PanelState>> } | null>(null);

/** One owner for header panels, including the phone panel's React portal. */
export function HeaderPanelProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<PanelState>(null);
  const value = useMemo(() => ({ active, setActive }), [active]);
  return <HeaderPanels.Provider value={value}>{children}</HeaderPanels.Provider>;
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
