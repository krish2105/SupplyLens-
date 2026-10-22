import { expect, type Page } from "@playwright/test";
import { provenDisposable } from "./disposable";

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
