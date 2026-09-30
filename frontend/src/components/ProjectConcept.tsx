import { useState } from "react";
import { makerCatalog, structuralParts, type ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { systemText } from "../lib/systemText";

export type ProjectGenerationPhase = "design" | "image";

/** Presentation only: the App-owned cloud job supplies the actual phase. */
export function ProjectGenerationStatus({ phase, compact = false }: { phase: ProjectGenerationPhase; compact?: boolean }) {
  const tr = useMakerText();
  return <div className={`project-generation-status${compact ? " is-compact" : " project-image-empty"}`} role="status" aria-live="polite" aria-atomic="true" data-phase={phase}>
    <div className="project-generation-orbit" aria-hidden="true"><span>✧</span></div>
    <div className="project-generation-copy">
      <h3>{phase === "image" ? tr("正在生成作品圖片", "Generating your project image") : tr("AI 正在推論中", "AI is thinking")}<span className="project-generation-dots" aria-hidden="true"><i /><i /><i /></span></h3>
      <p>{compact ? tr("目前圖片會保留，可先切換頁面。", "Your current image stays visible; you can switch pages.") : phase === "image" ? tr("正在產生作品組裝圖片，可先切換頁面。", "Creating the assembly image; you can switch pages.") : tr("正在處理你的需求，完成後會更新結果。", "Working on your request. Results will appear when ready.")}</p>
    </div>
  </div>;
}

/** Actual persisted image only. Never substitute a schematic or a stock demo. */
export function ProjectConcept({ design, generationPhase }: { design: ProjectDesign; generationPhase?: ProjectGenerationPhase }) {
  const tr = useMakerText();
  const { tx, locale } = useI18n();
  const [failedURL, setFailedURL] = useState("");
  const image = design.image;
  const imageVisible = image && failedURL !== image.url;
  return <div className="project-image-concept">
    {generationPhase && imageVisible ? <ProjectGenerationStatus phase={generationPhase} compact /> : null}
    {imageVisible ? <figure>
      <a href={image.url} target="_blank" rel="noreferrer" aria-label={tr("開啟完整作品圖片", "Open full project image")}>
        <img src={image.url} width={image.width} height={image.height} alt={design.title + " — " + tr("AI 模組組裝示意圖", "AI modular assembly illustration")} onError={() => setFailedURL(image.url)} />
      </a>
      <figcaption><span>AI GENERATED · {tr("組裝示意", "ASSEMBLY CONCEPT")}</span><a href={image.url} target="_blank" rel="noreferrer">{tr("查看大圖 ↗", "Full image ↗")}</a></figcaption>
    </figure> : generationPhase ? <ProjectGenerationStatus phase={generationPhase} /> : <div className="project-image-empty" role="status"><span aria-hidden="true">✧</span>
      <h3>{design.image_error ? tr("圖片未生成成功", "Image generation failed") : image ? tr("圖片無法載入", "Image unavailable") : tr("這個版本尚未生成作品圖片", "This revision has no generated image")}</h3>
      <p>{design.image_error ? systemText(design.image_error, locale) : tr("在左側送出設計／修改需求，雲端 AI 會產生真正的作品組裝圖片。", "Submit a design or revision on the left to generate an actual assembly image.")}</p>
      {image ? <button onClick={() => setFailedURL("")}>{tr("重新載入圖片", "Reload image")}</button> : null}
    </div>}
    <div className="project-scope"><span>Raspberry Pi 5</span>{design.component_ids.map(id => <span key={id}>{tx(makerCatalog.modules.find(m => m.id === id)!.name)}</span>)}</div>
    {design.assembly ? <details className="project-assembly-details" key={`${design.id}:${design.revision}`}><summary>{tr("造型與結構", "Shape & structure")}</summary><p>{design.assembly.description}</p><div className="project-structure-tags">{design.assembly.parts.map(p => <span key={p.kind}>{systemText(structuralParts[p.kind].name, locale)} × {p.quantity}</span>)}</div></details> : null}
  </div>;
}
