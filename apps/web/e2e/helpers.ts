import { expect, type Page } from "@playwright/test";
import { provenDisposable } from "./disposable";
import { lockReferenceCase } from "./fixtures";

export async function signIn(page: Page, role: "viewer" | "planner" | "approver" | "tenant_admin") {
  await page.request.post("/api/v1/auth/dev-login", {
    headers: { "X-Requested-With": "supplylens" }, data: { email: `${role}@dev.supplylens.local` },
  });
}

/** GET a tenant-scoped API path with the current session (the page must already be signed in). */
export async function getJson<T = any>(page: Page, path: string, ws = "uci-research"): Promise<T> {
  const r = await page.request.get(path, { headers: { "X-SupplyLens-Tenant": ws } });
  if (!r.ok()) throw new Error(`${path}: ${r.status()}`);
  return r.json() as Promise<T>;
}

/** Wait until THIS action is reconciled. Not `getByText("RECONCILED")`: approvals lists other, already reconciled actions. */
export async function expectReconciled(page: Page, actionId: string, ws = "demo") {
  await expect.poll(async () => (await getJson<{ status: string }>(page, `/api/v1/actions/${actionId}`, ws)).status,
    { timeout: 30_000, message: `action ${actionId} should reach RECONCILED` }).toBe("RECONCILED");
  // keep the reference case repeatable: release this test order's open units (audited; see global-setup.ts), only on a
  // stack proven disposable (e2e/disposable.ts)
  if (!provenDisposable()) return;
  const lines = await getJson<{ action_id: string; sku_id: string; open_units: number }[]>(page, "/api/v1/open-orders", ws);
  for (const l of lines.filter((x) => x.action_id === actionId && x.open_units > 0)) {
    await page.request.post(`/api/v1/actions/${actionId}/cancel-open`, { headers: { "X-SupplyLens-Tenant": ws, "X-Requested-With": "supplylens" },
      data: { sku_id: l.sku_id, reason: "e2e: release test order" } });
  }
}

const REFERENCE_RUN = {
  mode: "draft", sku_ids: ["DEMO-REF-SKU"], knowledge_cutoff: "2026-10-20T09:00:00Z", effective_date: "2026-10-20",
  budget_minor: 18000, currency: "USD", allow_shortfall: false,
};

/** Signs in as a planner and has the investigator prepare the reference-case draft in the Demo workspace. */
export async function createDraft(page: Page): Promise<string> {
  await lockReferenceCase();
  await signIn(page, "planner");
  const H = { "X-SupplyLens-Tenant": "demo", "X-Requested-With": "supplylens" };
  const r = await page.request.post("/api/v1/agent-runs", { headers: { ...H, "Idempotency-Key": crypto.randomUUID() }, data: REFERENCE_RUN });
  const { run_id } = await r.json();
  for (let i = 0; i < 60; i++) {
    const d = await (await page.request.get(`/api/v1/agent-runs/${run_id}`, { headers: H })).json();
    if (!["QUEUED", "RUNNING"].includes(d.status)) {
      if (!d.actions?.length) throw new Error(`run ${run_id} ended ${d.status} without a draft`);
      return d.actions[0].id as string;
    }
    await new Promise((res) => setTimeout(res, 500));
  }
  throw new Error("run did not finish");
}

/** Make WebGL unavailable before any page script runs. `afterFirstProbe` lets the capability probe succeed once. */
export async function breakWebGL(page: Page, afterFirstProbe = false) {
  await page.addInitScript((lateFailure) => {
    const orig = HTMLCanvasElement.prototype.getContext;
    let probes = 0;
    // @ts-expect-error test shim
    HTMLCanvasElement.prototype.getContext = function (type: string, ...rest: unknown[]) {
      if (/webgl/i.test(type)) {
        probes += 1;
        if (!lateFailure || probes > 1) return null;
      }
      return orig.call(this, type, ...rest);
    };
  }, afterFirstProbe);
}

/**
 * A fresh customer workspace onboarded through the product's own CSV imports (one SKU, 120 days of sales, a stock
 * snapshot, one supplier term), with the dev planner and approver as members. For journeys that change stock for good
 * (receipts are an append-only ledger), so they never disturb the shared Demo reference case.
 */
export async function onboardWorkspace(page: Page): Promise<{ slug: string; asOf: string }> {
  await signIn(page, "tenant_admin");
  const slug = `e2e-rcv-${Date.now().toString(36)}`;
  const H = { "X-Requested-With": "supplylens" };
  const created = await page.request.post("/api/v1/onboarding/workspaces", { headers: { ...H, "X-SupplyLens-Tenant": "uci-research", "Idempotency-Key": crypto.randomUUID() },
    data: { slug, name: `E2E receipts ${slug}`, currency: "GBP", weekly_budget_minor: 500000, coverage_days: 14 } });
  if (!created.ok()) throw new Error(`workspace: ${created.status()} ${await created.text()}`);
  const W = { ...H, "X-SupplyLens-Tenant": slug };
  const start = Date.UTC(2026, 4, 1);
  const sales = ["day,sku_id,location_id,units", ...Array.from({ length: 120 }, (_, i) =>
    `${new Date(start + i * 86_400_000).toISOString().slice(0, 10)},SKU-1,WH-01,${(i % 7) + 3}`)].join("\n");
  const files: [string, string][] = [["sales", sales],
    ["stock", "as_of,location_id,sku_id,on_hand,allocated,on_order,capacity\n2026-08-28,WH-01,SKU-1,20,0,0,500\n"],
    ["terms", "term_id,supplier_id,supplier_name,sku_id,unit_cost_minor,currency,moq,order_multiple,lead_time_days,valid_from,valid_to,known_at\n" +
      "T-1,SUP-A,Acme,SKU-1,450,GBP,20,10,5,2026-01-01,,2025-12-01T00:00:00Z\n"]];
  for (const [kind, csv] of files) {
    const up = await page.request.post("/api/v1/onboarding/batches", { headers: { ...W, "Idempotency-Key": crypto.randomUUID() },
      multipart: { kind, rights: "e2e fixture, synthetic", file: { name: `${kind}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) } } });
    if (!up.ok()) throw new Error(`${kind} upload: ${up.status()} ${await up.text()}`);
    const b = await up.json();
    const v = await page.request.post(`/api/v1/onboarding/batches/${b.id}/validate`, { headers: { ...W, "Idempotency-Key": crypto.randomUUID() }, data: { mapping: b.mapping } });
    if (!v.ok()) throw new Error(`${kind} validate: ${v.status()} ${await v.text()}`);
    const pub = await page.request.post(`/api/v1/onboarding/batches/${b.id}/publish`, { headers: { ...W, "Idempotency-Key": crypto.randomUUID() } });
    if (!pub.ok()) throw new Error(`${kind} publish: ${pub.status()} ${await pub.text()}`);
  }
  for (const [email, role] of [["planner@dev.supplylens.local", "planner"], ["approver@dev.supplylens.local", "approver"]]) {
    const m = await page.request.post("/api/v1/admin/members", { headers: { ...W, "Idempotency-Key": crypto.randomUUID() }, data: { email, role } });
    if (!m.ok()) throw new Error(`member ${email}: ${m.status()} ${await m.text()}`);
  }
  return { slug, asOf: "2026-08-28" };
}

/** Starts an investigation in draft mode and waits for it to finish; returns its action ids. */
export async function runInvestigation(page: Page, ws: string, body: Record<string, unknown>): Promise<string[]> {
  const H = { "X-SupplyLens-Tenant": ws, "X-Requested-With": "supplylens" };
  const r = await page.request.post("/api/v1/agent-runs", { headers: { ...H, "Idempotency-Key": crypto.randomUUID() }, data: { mode: "draft", ...body } });
  if (r.status() !== 202) throw new Error(`run: ${r.status()} ${await r.text()}`);
  const { run_id } = await r.json();
  await expect.poll(async () => (await (await page.request.get(`/api/v1/agent-runs/${run_id}`, { headers: H })).json()).status,
    { timeout: 30_000 }).not.toMatch(/^(QUEUED|RUNNING)$/);
  const d = await (await page.request.get(`/api/v1/agent-runs/${run_id}`, { headers: H })).json();
  return (d.actions ?? []).map((a: { id: string }) => a.id);
}
