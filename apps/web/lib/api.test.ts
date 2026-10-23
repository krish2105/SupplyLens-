import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, busySignal, intentKey } from "./api";

type Call = { url: string; key: string | null; method: string };

function mockFetch(responses: { status: number; body?: unknown; headers?: Record<string, string> }[]) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const h = new Headers(init.headers);
    calls.push({ url, key: h.get("Idempotency-Key"), method: String(init.method) });
    const r = responses.shift() ?? { status: 200, body: {} };
    return new Response(r.body === undefined ? "" : JSON.stringify(r.body),
      { status: r.status, headers: { "content-type": "application/json", ...(r.headers ?? {}) } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

/** The ApiError a request is expected to fail with. */
const failure = (p: Promise<unknown>) => p.then(() => { throw new Error("expected the request to fail"); }, (e: unknown) => e as ApiError);

describe("idempotency keys per user intent (P2-FE-05)", () => {
  it("reuses the key when the same intent is sent again after a failure, and releases it after success", async () => {
    const calls = mockFetch([{ status: 503, body: { code: "overloaded", message: "busy" } }, { status: 200, body: { ok: true } },
      { status: 200, body: { ok: true } }]);
    const send = () => api("/api/v1/admin/exports", { method: "POST", body: JSON.stringify({ include_vectors: false }), tenant: "t1" });
    await expect(send()).rejects.toBeInstanceOf(ApiError);
    await send();                                     // retry of the same intent: same key, so the server replays
    await send();                                     // after success: a deliberate repeat is a new intent
    expect(calls[0]!.key).toBe(calls[1]!.key);
    expect(calls[2]!.key).not.toBe(calls[1]!.key);
  });

  it("distinguishes intents by workspace, path and body", async () => {
    const calls = mockFetch([{ status: 500 }, { status: 500 }, { status: 500 }]);
    for (const [tenant, body] of [["a", "{\"x\":1}"], ["b", "{\"x\":1}"], ["a", "{\"x\":2}"]]) {
      await api("/api/v1/scenarios", { method: "POST", body, tenant }).catch(() => {});
    }
    expect(new Set(calls.map((c) => c.key)).size).toBe(3);
  });

  it("gives every file upload its own key and never keys GETs or sign-in", async () => {
    const calls = mockFetch([{ status: 500 }, { status: 500 }, { status: 200, body: {} }, { status: 200, body: {} }]);
    const form = () => { const f = new FormData(); f.append("file", new Blob(["a"]), "a.csv"); return f; };
    await api("/api/v1/onboarding/uploads", { method: "POST", body: form() }).catch(() => {});
    await api("/api/v1/onboarding/uploads", { method: "POST", body: form() }).catch(() => {});
    await api("/api/v1/overview");
    await api("/api/v1/auth/dev-login", { method: "POST", body: "{}" });
    expect(calls[0]!.key).not.toBe(calls[1]!.key);
    expect(calls[2]!.key).toBeNull();
    expect(calls[3]!.key).toBeNull();
  });

  it("an explicit intent key wins", async () => {
    const calls = mockFetch([{ status: 200, body: {} }]);
    const i = intentKey("custom", { a: 1 });
    await api("/api/v1/agent-runs", { method: "POST", body: "{}", idempotencyKey: i.key });
    expect(calls[0]!.key).toBe(i.key);
  });
});

describe("capacity refusals (Phase 3)", () => {
  it("marks 503 overloaded and 429 workspace_busy as busy, reads Retry-After and raises the busy signal", async () => {
    mockFetch([{ status: 503, body: { code: "overloaded", message: "at capacity" }, headers: { "Retry-After": "3" } },
      { status: 429, body: { code: "workspace_busy", message: "busy" } }, { status: 429, body: { code: "rate_limited", message: "slow" } }]);
    const e1 = await failure(api("/api/v1/inventory"));
    expect(e1.busy && e1.retryAfter === 3 && e1.message === "at capacity").toBe(true);
    expect(busySignal.snapshot()).toBe(true);
    expect((await failure(api("/api/v1/inventory"))).busy).toBe(true);
    expect((await failure(api("/api/v1/inventory"))).busy).toBe(false);   // a rate limit is not capacity
  });

  it("keeps the status and reference of an HTML gateway error instead of a parse failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502, headers: { "content-type": "text/html", "x-trace-id": "abc123" } })));
    const e = await failure(api("/api/v1/overview"));
    expect([e.status, e.code, e.reference]).toEqual([502, "bad_gateway_response", "abc123"]);
  });

  it("reports a request that never got a response as offline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const e = await failure(api("/api/v1/overview"));
    expect(e.offline).toBe(true);
  });
});
