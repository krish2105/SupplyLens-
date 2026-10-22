import { request, type FullConfig } from "@playwright/test";

/**
 * The Demo reference case needs 30 units net of open SupplyLens orders (audit S12). Orders reconciled by earlier runs
 * of this suite would otherwise cover it, so the suite starts by releasing their open units through the audited
 * cancel-open API (nothing is deleted; the ledger keeps every line with its cancellation).
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]!.use.baseURL!;
  const ctx = await request.newContext({ baseURL });
  await releaseOpenOrders(ctx);
  await ctx.dispose();
}

export async function releaseOpenOrders(ctx: Awaited<ReturnType<typeof request.newContext>>) {
  const H = { "X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo" };
  await ctx.post("/api/v1/auth/dev-login", { headers: H, data: { email: "planner@dev.supplylens.local" } });
  const lines = await (await ctx.get("/api/v1/open-orders", { headers: H })).json() as { action_id: string; sku_id: string; open_units: number }[];
  for (const l of lines.filter((x) => x.open_units > 0)) {
    await ctx.post(`/api/v1/actions/${l.action_id}/cancel-open`, { headers: H, data: { sku_id: l.sku_id, reason: "e2e suite: release test order" } });
  }
}
