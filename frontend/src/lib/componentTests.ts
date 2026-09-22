import { makerRequest, wireSignature, type MakerState, type ProjectDesign, type ProjectGuideState } from "./maker";
import type { PiExecutionStatus } from "./piApi";

export interface ComponentTestRun {
  id: string; project_id: string; revision: number; component_id: string; guide_key: string;
  template_version: string; wiring_hash: string; created_at: number; finished_at?: number;
  outcome: "running" | "awaiting_confirmation" | "passed" | "failed" | "inconclusive";
  phase: string; reason: string | null; detail: string; logs: string[];
  samples: Record<string, { count: number; median_cm: number | null }>;
  latest: { cm: number; at: number } | null; heartbeat_at: number | null;
  sample_count?: number; exit_code: number | null; reserved: boolean;
  program_stopped: boolean; invalidated: boolean; options: string[];
  program_stop_requested?: boolean; target_id?: string; failed_phase?: string; latest_valid_at?: number;
  evidence?: string;
}
export interface ComponentTestStatus {
  connected: boolean; test_busy: boolean; active: ComponentTestRun | null; results: ComponentTestRun[];
  ok?: boolean; error?: string;
  execution?: PiExecutionStatus;
}
export function componentComplete(design: ProjectDesign, session: ProjectGuideState, cid: string) {
  const wires = design.wiring.filter(w => w.componentId === cid);
  return wires.length > 0 && wires.every(w => session.confirmed[w.id]?.signature === wireSignature(w));
}
export function selectTestModule(design: ProjectDesign, session: ProjectGuideState, componentIndex: number): ProjectGuideState {
  const cid = design.component_ids[componentIndex];
  if (!cid) return session;
  const steps = design.wiring.filter(w => w.componentId === cid);
  const complete = componentComplete(design, session, cid);
  return { ...session, componentIndex, index: complete ? steps.length - 1 : 0,
    phase: complete ? "review" : "prepare", checks: [] };
}
export function componentTestKey(design: ProjectDesign, session: ProjectGuideState, cid: string) {
  return JSON.stringify([design.id, design.revision, session.run ?? 0, design.catalog_version,
    design.profile_versions?.[cid] ?? null, design.wiring.filter(w => w.componentId === cid).map(w =>
      [wireSignature(w), session.confirmed[w.id]?.at ?? null])]);
}
export function componentTestRequest(design: ProjectDesign, session: ProjectGuideState, cid: string) {
  return { project_id: design.id, revision: design.revision, component_id: cid,
    catalog_version: design.catalog_version, profile_versions: design.profile_versions ?? {},
    guide_key: componentTestKey(design, session, cid),
    wires: design.wiring.filter(w => w.componentId === cid).map(w => ({ componentId: w.componentId,
      componentPin: w.componentPin, boardPin: w.boardPin, connectionKind: w.connectionKind })) };
}

export function testBindings(state: Pick<MakerState, "design" | "guide">) {
  return state.design?.component_ids.map(cid => ({project_id:state.design!.id, component_id:cid,
    guide_key:componentTestKey(state.design!,state.guide,cid)})) ?? [];
}
export function changedTestBindings(previous: ReturnType<typeof testBindings>, next: ReturnType<typeof testBindings>) {
  return previous.filter(old => !next.some(current => current.project_id === old.project_id
    && current.component_id === old.component_id && current.guide_key === old.guide_key));
}
export async function invalidateEditedBindings(bindings: ReturnType<typeof testBindings>) {
  for (const projectId of new Set(bindings.map(b => b.project_id))) {
    const status = await makerRequest<ComponentTestStatus>(`pi/component-tests?project_id=${encodeURIComponent(projectId)}`);
    const queued = status.execution?.jobs.filter(job => job.kind === "test"
      && ["queued", "preflight", "awaiting_confirmation", "blocked"].includes(job.state)
      && bindings.some(b => b.project_id === job.project_id && b.component_id === job.component_id && b.guide_key === job.guide_key)) ?? [];
    for (const job of queued) await makerRequest(`pi/execution/${job.id}/action`, {action:"cancel"});
    const outdated = status.results.filter(run => !run.invalidated && bindings.some(b => b.project_id === run.project_id
      && b.component_id === run.component_id && b.guide_key === run.guide_key));
    for (const run of outdated) await makerRequest(`pi/component-tests/${run.id}/action`, {action:"invalidate",guide_key:run.guide_key});
  }
}

/** Explain only catalog-owned dependencies; never turn remote log text into an install command. */
export function missingDependencyMessage(detail: string, phase?: string): [string, string] | null {
  const matches = [...detail.matchAll(/ModuleNotFoundError: No module named ['"]([A-Za-z_][\w.]*)['"]/g)];
  const root = matches.at(-1)?.[1].split('.')[0];
  const packages: Record<string, string> = {
    luma: 'luma.lcd 2.13.0', PIL: 'Pillow', spidev: 'spidev', gpiozero: 'gpiozero', lgpio: 'lgpio', _lgpio: 'lgpio',
  };
  const name = root && Object.hasOwn(packages, root) ? packages[root] : undefined;
  if (!name) return null;
  const notStarted = phase === 'preflight';
  return [
    `Pi 測試環境缺少 ${name}。${notStarted ? '本次尚未啟動硬體測試；' : ''}請在 Board Vision 使用的虛擬環境補裝，再按「重新測試」。不必先重接線。`,
    `The Pi test environment is missing ${name}. ${notStarted ? 'Hardware testing has not started. ' : ''}Install it in the virtual environment used by Board Vision, then retry. Do not rewire yet.`,
  ];
}

export const testReasons: Record<string, [string, string]> = {
  executor_restart_required: ["請重新啟動 Board Vision 後端，啟用共用執行佇列後再測試。", "Restart the Board Vision backend to enable the shared execution queue before testing."],
  connection_lost: ["無法取得 Pi 目前狀態。請檢查電源／網路；尚未確認停止前不會啟動第二份測試。", "Pi status is unknown. Check power/network; another test cannot start until stop is confirmed."],
  missing_dependency: ["Pi 測試環境未準備好。請展開環境設定，先完成套件與虛擬環境準備，不必重接線。", "Pi test dependencies are missing. Expand setup instructions; do not rewire yet."],
  spi_missing: ["找不到 SPI0。請在 Pi 的 raspi-config 啟用 SPI，再依提示重新開機。", "SPI0 is missing. Enable SPI in raspi-config and reboot if prompted."],
  device_permission: ["目前 Pi 帳號無裝置存取權。請檢查 gpio／spi 群組權限。", "Check GPIO/SPI device permissions for the Pi account."],
  resource_busy: ["硬體正被使用。先停止本次測試或處理其他程式；系統不會強制停止無關程式。", "Hardware is busy. Stop this test or resolve the other program; unrelated programs are never killed."],
  program_error: ["測試程式未正常完成。展開診斷查看失敗階段與錯誤。", "The test did not finish normally. Expand diagnostics for the stage and error."],
  reader_error: ["測試背景讀取發生程式錯誤，已停止本次測試；不是判定沒有回波或接錯線。請重新測試，若仍出現請展開診斷。", "A background reader failed and this test stopped. This is not a no-echo or miswiring verdict. Retry; if it recurs, expand diagnostics."],
  no_progress: ["程式尚在執行，但一段時間沒有新回報或測試進度。可停止測試後重試。", "The process is running but reports or test progress have stalled. Stop and retry."],
  no_echo: ["新回波不足，尚不能判定接線。先放置平整目標物；仍無回波再查看本零件接線。", "Not enough fresh echoes. Place a flat target first, then review wiring if echoes remain absent."],
  movement_not_confirmed: ["未確認近、遠距離差異。請依提示明顯移遠目標物再測一次；不能直接判定接錯。", "Near/far movement was not confirmed. Move the target farther and retry; this does not prove miswiring."],
  display_black: ["已送出測試圖，但你回報全黑。先核對供電／背光規格，再檢查本零件接線；不要自行改接 5V 或 BLK。", "Image sent, but screen reported black. Check supply/backlight specifications and wiring; do not guess a 5V or BLK connection."],
  display_white: ["你回報白屏。請核對 SPI、CS、DC、RES 接線，再重測；白屏本身不能指出哪一支接錯。", "White screen reported. Review SPI, CS, DC and RES wiring and retry; it does not identify a specific bad pin."],
  display_abnormal: ["畫面／顏色異常。請核對接線及顯示方向，保留現象再重測。", "Image/colors are abnormal. Review wiring and orientation, record the symptom and retry."],
  wrong_visual_code: ["選擇的測試碼與本次不符，可能是舊畫面。請重新測試。", "The code does not match this run; it may be an old image. Retry."],
  timeout: ["本次測試已逾時，沒有判定通過。準備好後可重測。", "The test timed out without passing. Retry when ready."],
  cancelled: ["本次測試已停止，未記錄為通過。", "Test stopped; not recorded as passed."],
  wiring_changed: ["接線或本輪進度已修改，舊結果失效。完成接線後重新測試。", "Wiring or guide progress changed. Finish wiring and run a new test."],
  stale_test: ["這不是目前接線的測試，請更新狀態後重測。", "This test belongs to old wiring. Refresh status and retry."],
  no_result: ["程式已停止但沒有完整測試結果，不能判定通過。", "The process stopped without a complete result; success is unconfirmed."],
  remote_state_unknown: ["無法確認遠端程式是否停止，請先恢復連線。", "Cannot confirm whether the remote process stopped. Reconnect first."],
  interrupted: ["上次操作已中斷，請重新測試。", "The previous operation was interrupted. Run a new test."],
  catalog_changed: ["零件目錄已更新，請回到設計頁更新作品後重測。", "The catalog changed. Update the project on the design page and retry."],
  profile_changed: ["腳位 Profile 已更新，請回到設計頁更新作品並重新核對接線。", "The pin profile changed. Update the project and check its wiring again."],
};
