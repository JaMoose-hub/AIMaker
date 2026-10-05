import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

interface Target { element: HTMLDivElement | null; enabled: boolean }
interface GuideDock {
  target: Target;
  setTarget: (target: Target) => void;
  reveal: () => void;
  showing: boolean;
}
const ConversationGuideContext = createContext<GuideDock | null>(null);

/** Presentation bridge only. The existing project guide remains the sole owner. */
export function ConversationGuideProvider({ children, enabled, showing, onReveal }: {
  children: ReactNode; enabled: boolean; showing: boolean; onReveal: () => void;
}) {
  const [target, setTarget] = useState<Target>({ element: null, enabled: false });
  return <ConversationGuideContext.Provider value={enabled ? { target, setTarget, reveal: onReveal, showing } : null}>
    {children}
  </ConversationGuideContext.Provider>;
}

export const useConversationGuideDock = () => useContext(ConversationGuideContext);

/** Keep the destination mounted across chat/demo switches, preserving test UI. */
export function ConversationGuideHost({ enabled }: { enabled: boolean }) {
  const dock = useConversationGuideDock();
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => setElement(node), []);
  const setTarget = dock?.setTarget;
  useEffect(() => {
    setTarget?.({ element, enabled });
    return () => setTarget?.({ element: null, enabled: false });
  }, [setTarget, element, enabled]);
  return <div ref={ref} className="unified-conversation-guide" hidden={!enabled} />;
}
