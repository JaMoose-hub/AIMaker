import type { Dispatch, SetStateAction } from "react";
import type { MakerState } from "../lib/maker";
import type { useAIOptions } from "../lib/useAIOptions";
import { useMakerText } from "../lib/useMaker";

const effortNames: Record<string, [string, string]> = {
  none: ["不推理", "None"], minimal: ["最少", "Minimal"], low: ["低 · 較快", "Low · faster"],
  medium: ["中 · 平衡", "Medium · balanced"], high: ["高 · 深入", "High · deeper"],
  xhigh: ["非常高", "Extra high"], max: ["最高", "Maximum"],
};

export function AIModelControls({ state, setState, ai, busy }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>; ai: ReturnType<typeof useAIOptions>; busy: boolean;
}) {
  const tr = useMakerText();
  return <section className="maker-ai-settings" aria-label={tr("模型與費用設定", "Model and cost settings")}>
    <div className="maker-ai-selects">
      <label>{tr("AI 模型", "AI model")}<select value={state.aiModel} disabled={busy || !ai.options} onChange={event => {
        const model = event.target.value;
        const id = model || ai.options?.default_model;
        const option = ai.options?.models.find(m => m.id === id);
        setState(s => ({ ...s, aiModel: model, aiEffort: option?.efforts.includes(s.aiEffort) ? s.aiEffort : option?.default_effort ?? "low" }));
      }}>
        <option value="">{tr("Codex 預設", "Codex default")}{ai.options ? ` · ${ai.options.default_model}` : ""}</option>
        {state.aiModel && !ai.selectedModel ? <option value={state.aiModel} disabled>{state.aiModel} · {tr("目前不可用", "Unavailable")}</option> : null}
        {ai.options?.models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select></label>
      <label>{tr("推理強度", "Reasoning effort")}<select value={state.aiEffort} disabled={busy || !ai.selectedModel} onChange={event => setState(s => ({ ...s, aiEffort: event.target.value }))}>
        {!ai.selectedModel?.efforts.includes(state.aiEffort) ? <option value={state.aiEffort} disabled>{state.aiEffort} · {tr("請重新選擇", "Select again")}</option> : null}
        {ai.selectedModel?.efforts.map(effort => <option key={effort} value={effort}>{effortNames[effort] ? tr(...effortNames[effort]) : effort}</option>)}
      </select></label>
    </div>
    {ai.selectedModel?.description ? <small>{ai.selectedModel.description}</small> : null}
    {ai.selectedModel?.excluded_efforts.length ? <small>{tr("此工作台為單回合設計，不提供會自動委派其他 AI 的 ultra 模式。", "This single-turn designer excludes ultra, which delegates to other agents.")}</small> : null}
    {ai.selectedModel?.notice ? <small className="maker-warning">{ai.selectedModel.notice}</small> : null}
    {ai.options && !ai.selectionValid ? <p className="maker-warning">{tr("先前模型或推理強度目前不可用，請重新選擇；不會自動換模型送出。", "Saved model/effort is unavailable. Select again; no automatic model substitution.")}</p> : null}
    {ai.modelError ? <p className="maker-warning" role="alert">{ai.modelError}</p> : null}
    <button type="button" className="maker-text-button" onClick={ai.refresh} disabled={busy}>{tr("重新讀取模型／估算", "Reload models / estimate")}</button>
  </section>;
}

export function AICostPanel({ state, setState, ai, busy }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>; ai: ReturnType<typeof useAIOptions>; busy: boolean;
}) {
  const tr = useMakerText();
  const estimate = ai.estimate;
  const tokens = (range: { min: number; max: number }) => `${range.min.toLocaleString()}–${range.max.toLocaleString()}`;
  return <div className="maker-ai-settings">
    <div className="maker-ai-cost" aria-live="polite">
      <strong>{tr("雲端 AI 費用預估", "Cloud AI cost estimate")}</strong>
      {state.aiIntent === "design" ? <small className="maker-warning">{tr("以下僅為文字設計估算，不包含作品圖片生成／修改及其額外模型用量；圖片使用 Codex 額度，無法預先精確計價。", "Text-design estimate only. Excludes image generation / editing and its additional model usage. Images use Codex allowance; exact cost cannot be predicted.")}</small> : null}
      <small>{tr("目前使用 ChatGPT 登入／訂閱額度；下列 USD 是 API 等值參考，不是本次實際扣款。", "Using ChatGPT sign-in / plan allowance. USD below is an API-equivalent reference, NOT your actual charge.")}</small>
      {ai.estimating ? <p>{tr("估算中…（不呼叫 AI 生成）", "Estimating… (no AI generation)")}</p> : estimate ? <>
        <div className="maker-ai-price">{estimate.api_equivalent_usd
          ? `US$ ${estimate.api_equivalent_usd.min.toFixed(4)} – ${estimate.api_equivalent_usd.max.toFixed(4)}`
          : tr("無法估算金額", "Price unavailable")}</div>
        {estimate.reference_credits ? <small>{tr("標準速率參考", "Standard-rate reference")}: {estimate.reference_credits.min.toFixed(3)}–{estimate.reference_credits.max.toFixed(3)} credits</small> : null}
        {estimate.unavailable_reason ? <p className="maker-warning">{estimate.unavailable_reason === "unknown_price"
          ? tr("尚無此模型的已核實單價，不視為免費。", "No verified price for this model; this does not mean free.")
          : estimate.unavailable_reason === "pricing_stale" ? tr("單價資料超過 30 天，需更新後再估算。", "Pricing is over 30 days old and must be refreshed.")
          : tr("超出短上下文估價範圍，需另外確認長上下文費率。", "Outside the short-context estimate range; verify long-context pricing.")}</p> : null}
        <details><summary>{tr("計算方式與假設", "Calculation and assumptions")}</summary>
          <p>{tr("輸入", "Input")}: {tokens(estimate.input_tokens)} tokens<br />{tr("輸出＋推理", "Output + reasoning")}: {tokens(estimate.output_tokens)} tokens</p>
          <p>{tr("公式：(輸入 tokens × 輸入單價 ＋ 輸出 tokens × 輸出單價) ÷ 1,000,000。", "Formula: (input tokens × input rate + output tokens × output rate) ÷ 1,000,000.")}</p>
          {estimate.rates ? <p>{tr("每百萬 tokens", "Per million tokens")}: {tr("輸入", "Input")} US$ {estimate.rates.input} / {tr("輸出", "Output")} US$ {estimate.rates.output}</p> : null}
          <p>{tr("輸入包含需求、作品上下文、JSON 格式與 1,000–6,000 額外系統 tokens 假設，以 UTF-8 長度粗估，非精確 tokenizer。輸出依推理強度作情境假設，非官方保證。", "Input includes the prompt, project context, JSON schema and an assumed 1,000–6,000 system tokens, estimated from UTF-8 length, not an exact tokenizer. Output scenarios depend on effort and are not provider guarantees.")}</p>
        </details>
      </> : <p>{ai.estimateError || tr("選擇模型、填入需求與零件後會自動估算。", "Select a model, enter a prompt and choose parts to estimate.")}</p>}
      <details><summary>{tr("調整輸出量假設", "Adjust output assumption")}</summary>
        <label>{tr("預期輸出＋推理 tokens（選填）", "Expected output + reasoning tokens (optional)")}
          <input type="number" min="256" max="128000" step="1" disabled={busy} value={state.aiExpectedOutputTokens ?? ""}
            placeholder={tr("自動依推理強度", "Automatic by effort")}
            onChange={event => setState(s => ({ ...s, aiExpectedOutputTokens: event.target.value === "" ? null : Number(event.target.value) }))} /></label>
        <small>{tr("估算區間採此值的 0.5–1.5 倍；這不是輸出限制或扣款上限。", "Uses 0.5–1.5× this value as a scenario; NOT an output or spending limit.")}</small>
      </details>
      <small>{tr("粗估不含快取折扣、Fast 加速、額外工具、稅金或重試；實際用量可能超出區間。訂閱內含額度與 credits 扣款以帳戶為準，不會自動購買。", "Excludes cache discounts, Fast mode, extra tools, taxes and retries. Actual usage may exceed this range. Included allowance and credit charges depend on your account; no automatic purchases.")}</small>
      {estimate ? <small>{tr("單價核對", "Prices checked")}: {estimate.pricing_checked_at} · <a href={estimate.api_source} target="_blank" rel="noreferrer">API {tr("定價", "pricing")}</a> · <a href={estimate.credits_source} target="_blank" rel="noreferrer">Credits</a></small> : null}
    </div>
  </div>;
}
