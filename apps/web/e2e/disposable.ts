import type { APIRequestContext } from "@playwright/test";

/**
 * Positive proof that the target is a disposable test stack before the suite changes business data (it cancels test
 * orders so the reference case stays repeatable). All four must hold, or nothing is modified:
 *   1. the base URL is a loopback address;
 *   2. the server reports environment development or test;
 *   3. the server itself declares the stack disposable (SUPPLYLENS_E2E_DISPOSABLE=true on the API; refused in demo and
 *      production by the API's own configuration check);
 *   4. the runner opted in with SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE=1.
 * The verdict is published to the workers as SUPPLYLENS_E2E_PROVEN_DISPOSABLE by the global setup.
 */
export async function proveDisposable(ctx: APIRequestContext, baseURL: string): Promise<{ ok: boolean; why: string }> {
  const host = new URL(baseURL).hostname;
  if (!["localhost", "127.0.0.1", "::1", "[::1]"].includes(host)) return { ok: false, why: `base URL host ${host} is not loopback` };
  if (process.env.SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE !== "1") return { ok: false, why: "SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE is not 1" };
  const r = await ctx.get("/api/v1/auth/config");
  if (!r.ok()) return { ok: false, why: `auth config answered HTTP ${r.status()}` };
  const cfg = await r.json() as { environment?: string; disposable?: boolean };
  if (!["development", "test"].includes(cfg.environment ?? "")) return { ok: false, why: `server environment is ${cfg.environment}` };
  if (cfg.disposable !== true) return { ok: false, why: "the server does not declare itself disposable (SUPPLYLENS_E2E_DISPOSABLE)" };
  return { ok: true, why: "loopback, development/test, server-declared disposable, runner opted in" };
}

export const provenDisposable = () => process.env.SUPPLYLENS_E2E_PROVEN_DISPOSABLE === "1";
