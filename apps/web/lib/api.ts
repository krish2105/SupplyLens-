"use client";
// Thin typed client for /api/v1 (proxied same-origin by Next). Server validation is authoritative.

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body?: unknown) {
    super(message);
  }
}

let tenantSlug = "uci-research";
export function setTenant(slug: string) { tenantSlug = slug; }
export function getTenant() { return tenantSlug; }

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now() + Math.random());
}

export async function api<T = unknown>(path: string, init: RequestInit & { idempotencyKey?: string; tenant?: string } = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "supplylens");
  headers.set("X-SupplyLens-Tenant", init.tenant ?? tenantSlug);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (method !== "GET" && !path.startsWith("/api/v1/auth")) headers.set("Idempotency-Key", init.idempotencyKey ?? newKey());
  const res = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, body?.code ?? "error", body?.message ?? res.statusText, body);
  }
  return body as T;
}

export const post = <T,>(path: string, body: unknown, opts: { idempotencyKey?: string } = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body), ...opts });
