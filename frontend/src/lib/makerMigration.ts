import { makerCatalog, makerRequest, restoreMaker } from "./maker";

export const MAKER_STORAGE = "boardvision.maker.v1";
export const RETIREMENT_BACKUP = "boardvision.maker.v1.before-hw123-removal";

export function needsRetirementMigration(raw: string | null): boolean {
  if (!raw) return false;
  try {
    const state = JSON.parse(raw);
    return [state.selected, state.design?.component_ids, state.candidate?.component_ids]
      .some(ids => Array.isArray(ids) && ids.some(id => makerCatalog.retired_module_ids.includes(id)));
  } catch { return false; }
}

/** Run before React mounts, so autosave and demo initialization cannot erase a legacy draft. */
export async function migrateStoredMaker(storage: Storage, request = makerRequest): Promise<void> {
  const raw = storage.getItem(MAKER_STORAGE);
  if (!needsRetirementMigration(raw)) return;
  // Failure to write this backup aborts migration; never overwrite the only copy.
  if (!storage.getItem(RETIREMENT_BACKUP)) storage.setItem(RETIREMENT_BACKUP, raw!);
  const result = await request<unknown>("design/migrate-retired", JSON.parse(raw!));
  if (!result || typeof result !== "object" || !("design" in result) || !("selected" in result)) {
    throw new Error("作品轉換資料不符；原草稿已保留。");
  }
  const serialized = JSON.stringify(result);
  const restored = restoreMaker(serialized);
  if (needsRetirementMigration(serialized) || (result as { design?: unknown })?.design && !restored.design) {
    throw new Error("作品轉換資料不符；原草稿已保留。");
  }
  storage.setItem(MAKER_STORAGE, serialized);
}
