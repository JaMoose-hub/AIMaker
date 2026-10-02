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

// Presentation-only sample for the built-in, full-kit Demo. Never persist this as
// a generated artifact or send it as a previous AI image/edit target.
const demoSample = { url: "/demo/distance-monitor-three-wheel-motors-v2.png", width: 1536, height: 1024 };
const demoConceptParts = [{ kind: "motor", quantity: 2 }] as const;

/** AI revisions show only their actual image; explicit Demo data may show a labelled sample. */
export function ProjectConcept({ design, generationPhase }: { design: ProjectDesign; generationPhase?: ProjectGenerationPhase }) {
  const tr = useMakerText();
  const { tx, locale } = useI18n();
  const [failedURL, setFailedURL] = useState("");
  const isDemoSample = design.source === "demo" && !design.image && !design.image_required
    && !design.image_error && !design.image_job_id && !design.concept_only_parts?.length
    && design.component_ids.length === 2 && design.component_ids.includes("hc-sr04") && design.component_ids.includes("mrd-tf240-8p-cs");
  const image = design.image ?? (isDemoSample ? demoSample : undefined);
  const conceptParts = isDemoSample ? demoConceptParts : design.concept_only_parts;
  const imageVisible = image && failedURL !== image.url;
  return <div className="project-image-concept">
    {generationPhase && imageVisible ? <ProjectGenerationStatus phase={generationPhase} compact /> : null}
    {imageVisible ? <figure>
      <a href={image.url} target="_blank" rel="noreferrer" aria-label={tr("開啟完整作品圖片", "Open full project image")}>
        <img src={image.url} width={image.width} height={image.height} alt={isDemoSample ? tr("內建 Demo：三個輪胎、兩顆馬達、Pi 5、HC-SR04+ 與 TFT 螢幕的組裝外觀示意，非接線驗證", "Built-in Demo: three wheels, two motors, Pi 5, HC-SR04+ and TFT display assembly illustration, not wiring verification") : design.title + " — " + tr("AI 模組組裝示意圖", "AI modular assembly illustration")} onError={() => setFailedURL(image.url)} />
      </a>
      <figcaption><span title={isDemoSample ? tr("固定外觀示意，非本次 AI 生成；零件與接線請依製作藍圖。", "Fixed sample, not generated in this session. Follow the blueprint for parts and wiring.") : undefined}>{isDemoSample ? tr("DEMO · 內建示範圖（非本次生成）", "DEMO · BUILT-IN SAMPLE (NOT GENERATED NOW)") : <>AI GENERATED · {tr("組裝示意", "ASSEMBLY CONCEPT")}</>}</span><a href={image.url} target="_blank" rel="noreferrer">{tr("查看大圖 ↗", "Full image ↗")}</a></figcaption>
    </figure> : generationPhase ? <ProjectGenerationStatus phase={generationPhase} /> : <div className="project-image-empty" role="status"><span aria-hidden="true">✧</span>
      <h3>{design.image_error ? tr("圖片未生成成功", "Image generation failed") : image ? tr("圖片無法載入", "Image unavailable") : tr("這個版本尚未生成作品圖片", "This revision has no generated image")}</h3>
      <p>{isDemoSample ? tr("示範圖無法載入，請重新載入圖片或重新整理頁面；不會自動呼叫 AI 生圖。", "The sample image could not load. Reload the image or refresh the page; no AI generation will start automatically.") : design.image_error ? systemText(design.image_error, locale) : tr("在左側送出設計／修改需求，雲端 AI 會產生真正的作品組裝圖片。", "Submit a design or revision on the left to generate an actual assembly image.")}</p>
      {image ? <button onClick={() => setFailedURL("")}>{tr("重新載入圖片", "Reload image")}</button> : null}
    </div>}
    {conceptParts?.length ? <p className="project-concept-only maker-muted">
      {tr("僅概念圖", "Concept image only")} · {conceptParts.map(p => `${tr("馬達", "Motor")} × ${p.quantity}`).join(" · ")}
      {" — "}{tr("外觀示意，不含實際驅動；不納入藍圖、接線、測試或部署。", "Visual placeholders, not powered components; excluded from the blueprint, wiring, tests and deployment.")}
    </p> : null}
    <div className="project-scope"><span>Raspberry Pi 5</span>{design.component_ids.map(id => <span key={id}>{tx(makerCatalog.modules.find(m => m.id === id)!.name)}</span>)}</div>
    {design.assembly ? <details className="project-assembly-details" key={`${design.id}:${design.revision}`}><summary>{tr("造型與結構", "Shape & structure")}</summary><p>{design.assembly.description}</p><div className="project-structure-tags">{design.assembly.parts.map(p => <span key={p.kind}>{systemText(structuralParts[p.kind].name, locale)} × {p.quantity}</span>)}</div></details> : null}
  </div>;
}
