import type { CaptureTask } from "./debugSessions";
import type { ComponentPoseMessage } from "./types";

/** Scope presentation only; keep the detector packets and electrical checks intact. */
export function componentOverlayScope(
  selectedComponentId: string | null | undefined,
  guideComponentId: string | null | undefined,
  captureTask: CaptureTask | null,
  overview = false,
): string | null {
  if (captureTask?.wiring_target?.component_id) return captureTask.wiring_target.component_id;
  if (captureTask?.target === "hc_target") return "hc-sr04";
  if (captureTask?.target === "tft_screen") return "mrd-tf240-8p-cs";
  if (overview || captureTask?.target === "overview") return null;
  return selectedComponentId ?? guideComponentId ?? null;
}

export function componentPosesForOverlay(poses: ComponentPoseMessage[], componentId: string | null): ComponentPoseMessage[] {
  return componentId === null ? poses : poses.filter(pose => pose.component_id === componentId);
}
