import type { DebugContext } from "./debug";
import type { DebugSession } from "./debugSessions";
import type { WiringReviewState } from "./wiringReview";

export interface WiringReviewRecommendation {
  component_id: string;
  source: "test" | "ai";
}

const wiringReasons = new Set(["no_echo", "display_black", "display_white", "display_abnormal"]);
const softwareReasons = new Set(["missing_dependency", "spi_missing", "device_permission", "resource_busy", "program_error",
  "reader_error", "no_progress", "connection_lost", "remote_state_unknown", "environment_unknown", "syntax_error",
  "different_program", "execution_changed", "display_stalled", "executor_restart_required", "telemetry_unknown"]);

/** Recommendations only offer an entry. They never start capture, analysis or testing. */
export function recommendWiringReview(record: DebugSession | null | undefined, context: DebugContext, current: boolean): WiringReviewRecommendation | null {
  const project = context.project;
  if (!record || !project || !current || record.current_target === false || record.camera_current === false ||
    record.phase === "backend_restarted" || record.binding?.project_id !== project.id) return null;
  const components = project.component_ids;
  const latestTests = components.map(id => [...(record.test_results ?? [])].reverse().find(run => run.component_id === id))
    .filter(run => run && !run.invalidated && Boolean(context.test_keys[run.component_id]) && run.guide_key === context.test_keys[run.component_id]);
  const issues = record.diagnosis?.issues ?? [];
  if (softwareReasons.has(record.hardware_blocker ?? "") || softwareReasons.has(record.diagnosis?.hardware_blocker ?? "") ||
    issues.some(issue => softwareReasons.has(issue.reason)) ||
    latestTests.some(run => run && ["failed", "inconclusive"].includes(run.outcome) && softwareReasons.has(run.reason ?? ""))) return null;

  const test = latestTests.find(run => run && ["failed", "inconclusive"].includes(run.outcome) && wiringReasons.has(run.reason ?? ""));
  if (test) return { component_id: test.component_id, source: "test" };
  // The existing diagnosis also checks earlier component tests against their current guide keys.
  const issue = issues.find(item => item.component_id && components.some(id => id === item.component_id) &&
    !latestTests.some(run => run?.component_id === item.component_id) && wiringReasons.has(item.reason) &&
    ["target_then_wiring", "display_symptom", "inspect_wiring"].includes(item.next_action));
  if (issue?.component_id) return { component_id: issue.component_id, source: "test" };

  const observation = record.observations.at(-1);
  if (observation?.suggested_action !== "inspect_wiring") return null;
  const target = observation.target === "hc_target" ? "hc-sr04" : observation.target === "tft_screen" ? "mrd-tf240-8p-cs"
    : record.wiring_target?.component_id ?? context.wiring_target?.component_id;
  return target && components.some(id => id === target) ? { component_id: target, source: "ai" } : null;
}

export function hasUnfinishedWiringReview(review: WiringReviewState | null | undefined): boolean {
  if (!review || ["stale", "error"].includes(review.status)) return false;
  if (["collecting", "analysing"].includes(review.status) || !review.results.length) return true;
  return review.results.some(row => review.reviews[row.wire_id]?.decision !== "confirmed" || review.reviews[row.wire_id]?.evidence_stale);
}
