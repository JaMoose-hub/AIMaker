import type { Asset, LocalAsset, Pairing } from "./types";
import { normalizeBase } from "./domain";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export class MobileApi {
  base: string;
  constructor(public pairing: Pairing) {
    this.base = normalizeBase(pairing.base_url);
  }
  url(path: string) {
    const resolved = new URL(path, this.base + "/");
    if (resolved.origin !== new URL(this.base).origin)
      throw Error("附件網址不屬於配對電腦");
    return resolved.toString();
  }
  headers() {
    return { Authorization: `Bearer ${this.pairing.token}` };
  }
  async request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    timeoutMs = 120000,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.base}/api/mobile${path}`, {
        method,
        headers: {
          ...this.headers(),
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await response
        .json()
        .catch(() => ({ detail: `HTTP ${response.status}` }));
      if (!response.ok)
        throw new ApiError(
          response.status,
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail ?? data),
        );
      return data as T;
    } finally {
      clearTimeout(timer);
    }
  }
  upload(
    asset: LocalAsset,
    onProgress: (fraction: number) => void,
  ): Promise<Asset> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${this.base}/api/mobile/assets`);
      xhr.setRequestHeader("Authorization", `Bearer ${this.pairing.token}`);
      xhr.timeout = 180000;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      };
      xhr.onerror = () => reject(Error("上傳中斷，附件已保留，可重試。"));
      xhr.ontimeout = () => reject(Error("上傳逾時，請重試。"));
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            onProgress(1);
            resolve(data as Asset);
          } else reject(new ApiError(xhr.status, data.detail ?? "上傳失敗"));
        } catch {
          reject(Error("電腦回傳無法讀取的上傳結果"));
        }
      };
      const form = new FormData();
      form.append("upload_id", asset.upload_id);
      form.append("width", String(asset.width));
      form.append("height", String(asset.height));
      if (asset.duration) form.append("duration", String(asset.duration));
      form.append("file", {
        uri: asset.uri,
        name: asset.name,
        type: asset.mime,
      } as unknown as Blob);
      xhr.send(form);
    });
  }
}
export async function pair(base: string, code: string): Promise<Pairing> {
  const base_url = normalizeBase(base);
  const response = await fetch(`${base_url}/api/mobile/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: code.trim(), device_name: "Tinkro Mobile" }),
  });
  const result = await response.json();
  if (!response.ok)
    throw new ApiError(response.status, result.detail ?? "配對失敗");
  return {
    base_url,
    token: result.token,
    session_id: result.session_id,
    conversation_id: result.conversation_id,
    context_id: result.context_id,
    title: result.title,
  };
}
