import { makerCatalog, makerRequest, restoreMaker } from "./maker";

export const MAKER_STORAGE = "boardvision.maker.v1";
export const RETIREMENT_BACKUP = "boardvision.maker.v1.before-hw123-removal";
export const CATALOG_BACKUP = "boardvision.maker.v1.before-tft-ili9341-v3";

export function needsCatalogMigration(raw: string | null): boolean {
  if (!raw) return false;
  try {
    const state = JSON.parse(raw);
    return [state.design, state.candidate].some(design => design && design.catalog_version !== makerCatalog.version);
  } catch { return false; }
}

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
  const retired = needsRetirementMigration(raw), catalog = needsCatalogMigration(raw);
  if (!retired && !catalog) return;
  // Failure to write this backup aborts migration; never overwrite the only copy.
  if (retired && !storage.getItem(RETIREMENT_BACKUP)) storage.setItem(RETIREMENT_BACKUP, raw!);
  if (catalog && !storage.getItem(CATALOG_BACKUP)) storage.setItem(CATALOG_BACKUP, raw!);
  const result = await request<unknown>(catalog ? "design/migrate-catalog" : "design/migrate-retired", JSON.parse(raw!));
  if (!result || typeof result !== "object" || !("design" in result) || !("selected" in result)) {
    throw new Error("作品轉換資料不符；原草稿已保留。");
  }
  const serialized = JSON.stringify(result);
  const restored = restoreMaker(serialized);
  const project = result as { design?: unknown; candidate?: unknown };
  if (needsRetirementMigration(serialized) || needsCatalogMigration(serialized)
      || project.design && !restored.design || project.candidate && !restored.candidate) {
    throw new Error("作品轉換資料不符；原草稿已保留。");
  }
  storage.setItem(MAKER_STORAGE, serialized);
}
