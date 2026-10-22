import { expect, test } from "@playwright/test";
import { expectReconciled, getJson, signIn } from "./helpers";

// P0 journey on the spec's reference case: investigate -> prepare draft -> approve -> sandbox order reconciled.
test("reference case: planner drafts, approver approves, sandbox order reconciles", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/runs?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByText("WAITING FOR APPROVAL").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Planned 1 SKU need\(s\): OPTIMAL, 1 line\(s\), total 180.00 USD/)).toBeVisible();
  const runUrl = new URL(page.url());
  const runId = runUrl.searchParams.get("run")!;
  const detail = await (await page.request.get(`/api/v1/agent-runs/${runId}`, { headers: { "X-SupplyLens-Tenant": "demo" } })).json();
  const actionId = detail.actions[0].id as string;
  expect(detail.actions[0].supplier_id).toBe("DEMO-REF-B");

  // The preparer cannot approve; viewers see no approve control.
  await signIn(page, "viewer");
  await page.goto(`/approvals?ws=demo&action=${actionId}`);
  await expect(page.getByText("Viewers cannot approve.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);

  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${actionId}`);
  await expect(page.getByRole("cell", { name: "30 unit" })).toBeVisible();
  await page.getByRole("button", { name: "Approve US$180.00" }).click();
  await expectReconciled(page, actionId);
  await expect(page.getByText("RECONCILED").first()).toBeVisible();
  await expect(page.getByText("sandbox order read back and matched payload")).toBeVisible();
});

test("amendment known before 20 Oct changes the decision (A on 19 Oct)", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/runs?ws=demo&known=2026-10-19T09:00:00.000Z&eff=2026-10-19");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByText(/total 150.00 USD/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/1 upcoming policy changes/)).toBeVisible();
});

test("theme choice persists across reload", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/settings?ws=uci-research");
  await page.getByRole("radio", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("radio", { name: "Light theme" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/light/);
});

test("selecting a table row selects the same product in the floor plan and detail", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=uci-research");
  await page.getByRole("tab", { name: "2D floor plan" }).click();
  const first = page.locator("tbody tr").first();
  const sku = (await first.locator(".num").first().textContent())!.trim();
  await first.click();
  await expect(page).toHaveURL(new RegExp(`sku=${sku}`));
  await expect(page.getByRole("button", { name: new RegExp(`^${sku},`) })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#detail-title")).toContainText(sku);
});

test("command palette jumps to a product", async ({ page }) => {
  await signIn(page, "viewer");
  const sku = (await getJson<{ items: { sku_id: string }[] }>(page, "/api/v1/inventory")).items[0]!.sku_id;
  await page.goto("/?ws=uci-research");
  await page.getByRole("button", { name: "Open command palette" }).click();
  await page.getByRole("combobox", { name: "Search pages, products and commands" }).fill(sku);
  // Products load when the palette opens; wait for the match like a person would before confirming it.
  await expect(page.getByRole("option", { name: new RegExp(`^${sku}`) })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`inventory.*sku=${sku}`));
  await expect(page.locator("#detail-title")).toContainText(sku);
});

test("tenant admin can export the audit trail; viewer cannot open administration", async ({ page }) => {
  await signIn(page, "tenant_admin");
  const r = await page.request.get("/api/v1/admin/audit.csv?ws=uci-research");
  expect(r.status()).toBe(200);
  expect((await r.text()).split("\n")[0]).toContain("action");
  await signIn(page, "viewer");
  await page.goto("/admin?ws=uci-research");
  await expect(page.getByText("Administrators only")).toBeVisible();
});

test("forecast lab refuses a replay the champion has already seen", async ({ page }) => {
  await signIn(page, "planner");
  const models = await getJson<{ family: string; status: string; training_cutoff: string | null }[]>(page, "/api/v1/models");
  const champion = models.find((m) => m.status === "CHAMPION" && m.family !== "seasonal_naive");
  test.skip(champion?.training_cutoff !== "2011-11-10", "needs the trained champion from the real UCI study (training cutoff 2011-11-10)");
  await page.goto("/forecast?ws=uci-research&sku=85123A&known=2011-10-01T23:59:00.000Z");
  await page.getByRole("button", { name: /Run forecast/ }).click();
  await expect(page.getByText(/trained on data up to 2011-11-10/)).toBeVisible();
});
