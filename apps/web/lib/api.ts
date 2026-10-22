"use client";
// Thin typed client for /api/v1 (proxied same-origin by Next). Server validation is authoritative.

import { buildUrl, type Args, type Body, type PathsWith, type Res } from "./contract";

export class ApiError extends Error {
  /** `reference` is the server trace id (x-trace-id) a user can quote; `offline` means no response arrived at all. */
  constructor(public status: number, public code: string, message: string, public body?: unknown, public reference?: string) {
    super(message);
  }
  get offline() { return this.status === 0; }
  get denied() { return this.status === 403; }
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
  if (method !== "GET" && !path.startsWith("/api/v1/auth")) headers.set("Idempotency-Key", init.idempotencyKey ?? newKey());
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
    throw new ApiError(res.status, body?.code ?? (isJson ? "error" : "bad_gateway_response"), body?.message ?? fallback, body, reference);
  }
  if (text && !isJson) throw new ApiError(res.status, "unexpected_response", "The server sent a response SupplyLens cannot read.", undefined, reference);
  if (text && isJson && body === null) throw new ApiError(res.status, "malformed_response", "The server sent a malformed response.", undefined, reference);
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
