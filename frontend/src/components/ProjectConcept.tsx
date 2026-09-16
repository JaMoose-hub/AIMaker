import { useState } from "react";
import { makerCatalog, structuralParts, type ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";

/** Actual persisted image only. Never substitute a schematic or a stock demo. */
export function ProjectConcept({ design }: { design: ProjectDesign }) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const [failedURL, setFailedURL] = useState("");
  const image = design.image;
  return <div className="project-image-concept">
    {image && failedURL !== image.url ? <figure>
      <a href={image.url} target="_blank" rel="noreferrer" aria-label={tr("開啟完整作品圖片", "Open full project image")}>
        <img src={image.url} width={image.width} height={image.height} alt={design.title + " — " + tr("AI 模組組裝示意圖", "AI modular assembly illustration")} onError={() => setFailedURL(image.url)} />
      </a>
      <figcaption><span>AI GENERATED · {tr("組裝示意", "ASSEMBLY CONCEPT")}</span><a href={image.url} target="_blank" rel="noreferrer">{tr("查看大圖 ↗", "Full image ↗")}</a></figcaption>
    </figure> : <div className="project-image-empty" role="status"><span aria-hidden="true">✧</span>
      <h3>{design.image_error ? tr("圖片未生成成功", "Image generation failed") : image ? tr("圖片無法載入", "Image unavailable") : tr("這個版本尚未生成作品圖片", "This revision has no generated image")}</h3>
      <p>{design.image_error || tr("在左側送出設計／修改需求，雲端 AI 會產生真正的作品組裝圖片。", "Submit a design or revision on the left to generate an actual assembly image.")}</p>
      {image ? <button onClick={() => setFailedURL("")}>{tr("重新載入圖片", "Reload image")}</button> : null}
    </div>}
    <div className="project-scope"><span>Raspberry Pi 5</span>{design.component_ids.map(id => <span key={id}>{tx(makerCatalog.modules.find(m => m.id === id)!.name)}</span>)}</div>
    {design.assembly ? <><p>{design.assembly.description}</p><div className="project-structure-tags">{design.assembly.parts.map(p => <span key={p.kind}>{structuralParts[p.kind].name} × {p.quantity}</span>)}</div></> : null}
  </div>;
}
