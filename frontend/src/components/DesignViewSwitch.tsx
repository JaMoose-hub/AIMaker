import { useMakerText } from "../lib/useMaker";

export type DesignView = "concept" | "blueprint";

export function DesignViewSwitch({ view, hasBlueprint, onChange }: {
  view: DesignView; hasBlueprint: boolean; onChange: (view: DesignView) => void;
}) {
  const tr = useMakerText();
  return <nav className="maker-design-views" aria-label={tr("設計與藍圖內容", "Design and blueprint views")}>
    <button type="button" aria-pressed={view === "concept"} className={view === "concept" ? "active" : ""}
      onClick={() => onChange("concept")}>{tr("作品概念", "Project concept")}</button>
    <button type="button" disabled={!hasBlueprint} aria-pressed={view === "blueprint"} className={view === "blueprint" ? "active" : ""}
      onClick={() => onChange("blueprint")}>{tr("製作藍圖", "Build blueprint")}</button>
  </nav>;
}
