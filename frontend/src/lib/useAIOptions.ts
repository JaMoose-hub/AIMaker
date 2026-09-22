import { useEffect, useState } from "react";
import { designRequest, makerRequest, type MakerState } from "./maker";

export interface AIModel { id: string; name: string; description: string; efforts: string[]; default_effort: string; is_default: boolean; excluded_efforts: string[]; notice?: string; input_modalities?: string[] }
export interface AIModelOptions { models: AIModel[]; default_model: string; billing_mode: "chatgpt" }
export interface AIRange { min: number; max: number }
export interface AIEstimate {
  model: string; effort: string; input_tokens: AIRange; output_tokens: AIRange; expected_output_tokens: number;
  api_equivalent_usd: AIRange | null; reference_credits: AIRange | null; pricing_checked_at: string;
  unavailable_reason: "unknown_price" | "pricing_stale" | "long_context" | null;
  api_source: string; credits_source: string; rates: { input: number; output: number } | null;
}

export function useAIOptions(state: MakerState, locale: string, loggedIn: boolean) {
  const [options, setOptions] = useState<AIModelOptions | null>(null);
  const [modelError, setModelError] = useState("");
  const [refreshId, setRefreshId] = useState(0);
  const [result, setResult] = useState<{ key: string; estimate?: AIEstimate; error?: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setModelError("");
    if (!loggedIn) { setOptions(null); return; }
    makerRequest<AIModelOptions>(`ai/models${refreshId ? "?refresh=true" : ""}`, undefined, controller.signal)
      .then(value => { if (!cancelled) setOptions(value); })
      .catch(error => { if (!cancelled) { setOptions(null); setModelError(String(error)); } });
    return () => { cancelled = true; controller.abort(); };
  }, [loggedIn, refreshId]);

  const selectedModel = options?.models.find(m => m.id === (state.aiModel || options.default_model));
  const selectionValid = Boolean(selectedModel?.efforts.includes(state.aiEffort));
  const requestKey = JSON.stringify(designRequest({...state, aiIntent: "auto"}, locale, selectedModel?.id ?? (state.aiModel || null)));
  const canEstimate = loggedIn && selectionValid && Boolean(state.prompt.trim()) && state.selected.length > 0;
  useEffect(() => {
    if (!canEstimate) return;
    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      makerRequest<AIEstimate>("ai/estimate", JSON.parse(requestKey), controller.signal)
        .then(estimate => { if (!cancelled) setResult({ key: requestKey, estimate }); })
        .catch(error => { if (!cancelled) setResult({ key: requestKey, error: String(error) }); });
    }, 450);
    return () => { cancelled = true; clearTimeout(timer); controller.abort(); };
  }, [requestKey, canEstimate, refreshId]);
  // A cost for an earlier prompt/model must never remain visible as the current estimate.
  const current = canEstimate && result?.key === requestKey ? result : null;
  return { options, selectedModel, modelError, selectionValid, estimate: current?.estimate,
    estimateError: current?.error, estimating: canEstimate && !current, requestKey,
    refresh: () => setRefreshId(v => v + 1) };
}
