"use client";
// Thin typed client for /api/v1 (proxied same-origin by Next). Server validation is authoritative.

import { buildUrl, type Args, type Body, type PathsWith, type Res } from "./contract";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body?: unknown) {
    super(message);
  }
}

let tenantSlug = "uci-research";
export function setTenant(slug: string) { tenantSlug = slug; }
export function getTenant() { return tenantSlug; }

export function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now() + Math.random());
}

export async function api<T = unknown>(path: string, init: RequestInit & { idempotencyKey?: string; tenant?: string } = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "supplylens");
  headers.set("X-SupplyLens-Tenant", init.tenant ?? tenantSlug);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (method !== "GET" && !path.startsWith("/api/v1/auth")) headers.set("Idempotency-Key", init.idempotencyKey ?? newKey());
  let res: Response;
  try {
    res = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    // fetch only rejects when no response arrived: offline, DNS, reset connection, server down.
    throw new ApiError(0, "network", "Connection lost. Your input is kept; retry when you are back online.");
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, body?.code ?? "error", body?.message ?? res.statusText, body);
  }
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
