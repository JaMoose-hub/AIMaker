import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, MobileApi, pair } from "../src/api";
const pairing = {
  base_url: "http://192.168.1.2:8000",
  token: "test-token",
  session_id: "s",
  conversation_id: "c",
  context_id: "ctx",
  title: "Project",
};
test("authenticated requests preserve idempotency and context fields", async () => {
  const original = globalThis.fetch;
  const calls: { url: string; options?: RequestInit }[] = [];
  globalThis.fetch = async (input, options) => {
    calls.push({ url: String(input), options });
    return new Response(JSON.stringify({ id: "c", messages: [] }), {
      status: 202,
    });
  };
  try {
    const api = new MobileApi(pairing);
    const body = {
      request_id: "retry-same",
      context_id: "ctx",
      text: "Photo question",
      asset_ids: ["a"],
    };
    await api.request("/messages", "POST", body);
    await api.request("/messages", "POST", body);
    assert.equal(calls[0].url, "http://192.168.1.2:8000/api/mobile/messages");
    assert.deepEqual(calls[0].options?.headers, {
      Authorization: "Bearer test-token",
      "Content-Type": "application/json",
    });
    assert.equal(calls[0].options?.body, calls[1].options?.body);
    assert.equal(
      "inherit_media" in JSON.parse(calls[0].options!.body as string),
      false,
    );
    assert.equal(
      api.url("/api/mobile/assets/a/file"),
      "http://192.168.1.2:8000/api/mobile/assets/a/file",
    );
    assert.throws(() => api.url("https://other.test/asset"));
  } finally {
    globalThis.fetch = original;
  }
});
test("pair persists only credential identifiers, not full desktop context", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        ...pairing,
        context: { large_private_payload: "not-in-SecureStore" },
        view: {},
        stream: {},
      }),
      { status: 200 },
    );
  try {
    const result = await pair(pairing.base_url, "123456");
    assert.deepEqual(result, pairing);
    assert.equal("context" in result, false);
  } finally {
    globalThis.fetch = original;
  }
});
test("HTTP context conflict surfaces as retryable error instead of success", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "mobile_context_changed" }), {
      status: 409,
    });
  try {
    await assert.rejects(
      () => new MobileApi(pairing).request("/messages", "POST", {}),
      (e: unknown) =>
        e instanceof ApiError &&
        e.status === 409 &&
        e.message === "mobile_context_changed",
    );
  } finally {
    globalThis.fetch = original;
  }
});
