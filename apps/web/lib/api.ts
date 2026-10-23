"use client";
// Thin typed client for /api/v1 (proxied same-origin by Next). Server validation is authoritative.

import { buildUrl, type Args, type Body, type PathsWith, type Res } from "./contract";

export class ApiError extends Error {
  /** `reference` is the server trace id (x-trace-id) a user can quote; `offline` means no response arrived at all;
   *  `retryAfter` is the server's Retry-After in seconds, when it sent one. */
  constructor(public status: number, public code: string, message: string, public body?: unknown, public reference?: string,
              public retryAfter?: number) {
    super(message);
  }
  get offline() { return this.status === 0; }
  get denied() { return this.status === 403; }
  /** The service (or this workspace's share of it) is at capacity: the request was refused before any work, so it is safe
   *  to send again after `retryAfter`. */
  get busy() {
    return (this.status === 503 && ["overloaded", "query_timeout"].includes(this.code))
      || (this.status === 429 && this.code === "workspace_busy");
  }
}

// When the service last refused a request for capacity; the connection banner reads it (useSyncExternalStore).
let busyUntil = 0;
const busyListeners = new Set<() => void>();
export const busySignal = {
  subscribe(cb: () => void) { busyListeners.add(cb); return () => { busyListeners.delete(cb); }; },
  snapshot: () => busyUntil > Date.now(),
};
function noteBusy(seconds: number) {
  busyUntil = Date.now() + Math.max(seconds, 2) * 1000 + 2000;
  busyListeners.forEach((cb) => cb());
  setTimeout(() => busyListeners.forEach((cb) => cb()), busyUntil - Date.now() + 50);
}

let tenantSlug = "uci-research";
export function setTenant(slug: string) { tenantSlug = slug; }
export function getTenant() { return tenantSlug; }

export function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now() + Math.random());
}

// One Idempotency-Key per user intent (audit F05): retrying the same intent (same scope and body) after a failure or a
// lost response reuses its key, so the server replays the first outcome instead of acting twice. The key is released
// when the intent succeeds; a later, deliberate repeat is a new intent with a new key.
const intents = new Map<string, string>();
export function intentKey(scope: string, body: unknown) {
  const id = scope + "\u0000" + JSON.stringify(body ?? null);
  let k = intents.get(id);
  if (!k) { k = newKey(); intents.set(id, k); }
  return { key: k, settle: () => intents.delete(id) };
}

const GATEWAY: Record<number, string> = {
  502: "The SupplyLens service is not reachable through the gateway (HTTP 502).",
  503: "The SupplyLens service is temporarily unavailable (HTTP 503).",
  504: "The SupplyLens service did not answer in time (HTTP 504).",
};

export async function api<T = unknown>(path: string, init: RequestInit & { idempotencyKey?: string; tenant?: string } = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "supplylens");
  headers.set("X-SupplyLens-Tenant", init.tenant ?? tenantSlug);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  // Every mutation carries one key per user intent (P2-FE-05): without an explicit key, the intent is this workspace, method,
  // path and body, so a double click or a retry after a lost response is the same request to the server (replayed, never
  // executed twice). The key is released once the intent succeeds; a later deliberate repeat is a new intent.
  let settle: (() => void) | undefined;
  if (method !== "GET" && !path.startsWith("/api/v1/auth")) {
    let key = init.idempotencyKey;
    if (!key && (init.body == null || typeof init.body === "string")) {
      const intent = intentKey(`${init.tenant ?? tenantSlug} ${method} ${path}`, init.body ?? null);
      key = intent.key;
      settle = intent.settle;
    }
    key ??= newKey();             // a file upload is identified by its bytes, not its form: one key per request
    headers.set("Idempotency-Key", key);
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    // fetch only rejects when no response arrived: offline, DNS, reset connection, server down.
    throw new ApiError(0, "network", "Connection lost. Your input is kept; retry when you are back online.");
  }
  const reference = res.headers.get("x-trace-id") ?? undefined;
  const text = await res.text();
  let body: { code?: string; message?: string } | null = null;
  const isJson = (res.headers.get("content-type") ?? "").includes("json");
  if (text && isJson) {
    try { body = JSON.parse(text); } catch { body = null; }
  }
  if (!res.ok) {
    // A proxy or gateway may answer with HTML (audit S22): never surface a parse error, keep the status and reference.
    const fallback = GATEWAY[res.status] ?? `The server answered HTTP ${res.status} without a readable message.`;
    const header = Number(res.headers.get("retry-after"));
    const retryAfter = Number.isFinite(header) && header > 0 ? header : undefined;
    const err = new ApiError(res.status, body?.code ?? (isJson ? "error" : "bad_gateway_response"), body?.message ?? fallback, body,
      reference, retryAfter);
    if (err.busy) noteBusy(retryAfter ?? 2);
    throw err;
  }
  if (text && !isJson) throw new ApiError(res.status, "unexpected_response", "The server sent a response SupplyLens cannot read.", undefined, reference);
  if (text && isJson && body === null) throw new ApiError(res.status, "malformed_response", "The server sent a malformed response.", undefined, reference);
  settle?.();
  return body as T;
}

/** Typed GET: response, path parameters and query come from the API contract. */
export function apiGet<P extends PathsWith<"get">>(path: P, args?: Args<P> & { tenant?: string; signal?: AbortSignal }) {
  return api<Res<P>>(buildUrl(path, args as { path?: object; query?: object } | undefined), { tenant: args?.tenant, signal: args?.signal });
}

/** Typed POST. Pass the same `idempotencyKey` when retrying a request after a network failure. */
export function apiPost<P extends PathsWith<"post">>(path: P, args: Args<P, "post"> & { body?: Body<P>; idempotencyKey?: string; tenant?: string }) {
  return api<Res<P, "post">>(buildUrl(path, args as { path?: object; query?: object }), {
    method: "POST", body: JSON.stringify(args.body ?? {}), idempotencyKey: args.idempotencyKey, tenant: args.tenant,
  });
}
