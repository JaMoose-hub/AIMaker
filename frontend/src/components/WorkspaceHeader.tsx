import type { ReactNode } from "react";

/** Layout only: the existing controls retain their state, requests and handlers. */
export function WorkspaceHeader({ brand, navigation, saveStatus, children }: {
  brand: ReactNode;
  navigation: ReactNode;
  saveStatus: ReactNode;
  children: ReactNode;
}) {
  return <header className="header maker-header maker-header-integrated">
    <div className="maker-header-main">{brand}{navigation}</div>
    <div className="workspace-toolbar maker-workflow-toolbar maker-header-controls">
      {children}
    </div>
    {saveStatus}
  </header>;
}
