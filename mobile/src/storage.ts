import * as SecureStore from "expo-secure-store";
import { Directory, File, Paths } from "expo-file-system";
import type { LocalAsset, Pairing, SavedDraft } from "./types";
const KEY = "tinkro.mobile.pairing.v1";
const root = new Directory(Paths.document, "tinkro");
function directory() {
  if (!root.exists) root.create({ intermediates: true, idempotent: true });
  return root;
}
export async function loadPairing(): Promise<Pairing | null> {
  const s = await SecureStore.getItemAsync(KEY);
  return s ? JSON.parse(s) : null;
}
export async function savePairing(p: Pairing | null) {
  if (p) await SecureStore.setItemAsync(KEY, JSON.stringify(p));
  else await SecureStore.deleteItemAsync(KEY);
}
export function loadDraft(key: string, legacySession?: string): SavedDraft {
  try {
    let f = new File(directory(), `${key}.json`);
    // Migrate an existing pairing's session-key draft before its token is replaced.
    if (!f.exists && legacySession)
      f = new File(directory(), `${encodeURIComponent(legacySession)}.json`);
    return f.exists
      ? JSON.parse(f.textSync())
      : { text: "", attachments: [], outbox: [] };
  } catch {
    return { text: "", attachments: [], outbox: [] };
  }
}
export function saveDraft(key: string, value: SavedDraft) {
  new File(directory(), `${key}.json`).write(JSON.stringify(value));
}
export function retainAsset(asset: LocalAsset): LocalAsset {
  const ext =
    asset.name
      .split(".")
      .pop()
      ?.replace(/[^a-zA-Z0-9]/g, "") || "bin";
  const dest = new File(directory(), `${asset.upload_id}.${ext}`);
  new File(asset.uri).copy(dest);
  return { ...asset, uri: dest.uri, size: dest.size };
}
export function releaseAsset(asset: LocalAsset) {
  try {
    const f = new File(asset.uri);
    if (f.uri.startsWith(root.uri) && f.exists) f.delete();
  } catch {
    /* Sent media cleanup may be retried at a later launch. */
  }
}
