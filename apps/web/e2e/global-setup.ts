import { request, type FullConfig } from "@playwright/test";
import { proveDisposable } from "./disposable";

/**
 * The Demo reference case needs 30 units net of open SupplyLens orders (audit S12). Orders reconciled by earlier runs
 * of this suite would otherwise cover it, so the suite starts by releasing their open units through the audited
 * cancel-open API (nothing is deleted; the ledger keeps every line with its cancellation).
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]!.use.baseURL!;
  const ctx = await request.newContext({ baseURL });
  try {
    const proof = await proveDisposable(ctx, baseURL);
    if (!proof.ok) {
      // Read-only runs (for example layout and accessibility checks against a hosted URL) may skip the reset explicitly.
      if (process.env.SUPPLYLENS_E2E_SKIP_RESET === "1") { console.log(`e2e: not resetting test orders (${proof.why})`); return; }
      throw new Error(`Refusing to modify business data: ${proof.why}. Run against a disposable stack ` +
        "(apps/web/e2e/disposable.ts) or set SUPPLYLENS_E2E_SKIP_RESET=1 for a read-only run.");
    }
    process.env.SUPPLYLENS_E2E_PROVEN_DISPOSABLE = "1";
    await releaseOpenOrders(ctx);
  } finally {
    await ctx.dispose();
  }
}

export async function releaseOpenOrders(ctx: Awaited<ReturnType<typeof request.newContext>>) {
  const H = { "X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo" };
  // Orders committed but not reconciled also count as supply (P1-ACT-02): settle them first, through the same audited
  // paths a person would use, so their units land in the ledger and can be released below.
  await ctx.post("/api/v1/auth/dev-login", { headers: H, data: { email: "approver2@dev.supplylens.local" } });
  const mismatched = await (await ctx.get("/api/v1/actions?status=CONFIRMED", { headers: H })).json() as { id: string }[];
  for (const a of mismatched) {
    await ctx.post(`/api/v1/actions/${a.id}/accept-remote`, { headers: H, data: { reason: "e2e suite: settle a test order" } });
  }
  await ctx.post("/api/v1/auth/dev-login", { headers: H, data: { email: "planner@dev.supplylens.local" } });
  const unknown = await (await ctx.get("/api/v1/actions?status=UNKNOWN_OUTCOME", { headers: H })).json() as { id: string }[];
  for (const a of unknown) await ctx.post(`/api/v1/actions/${a.id}/reconcile`, { headers: H });
  const lines = await (await ctx.get("/api/v1/open-orders", { headers: H })).json() as { action_id: string; sku_id: string; open_units: number }[];
  for (const l of lines.filter((x) => x.open_units > 0)) {
    await ctx.post(`/api/v1/actions/${l.action_id}/cancel-open`, { headers: H, data: { sku_id: l.sku_id, reason: "e2e suite: release test order" } });
  }
}
