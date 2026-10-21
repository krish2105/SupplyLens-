import { expect, test } from "@playwright/test";
import { createDraft, getJson, signIn } from "./helpers";

// EXE-006: selection, filters and clock changes propagate across chart, table, floor plan, evidence and the action
// drawer without ever mixing run versions.

test("a forecast that returns after the user moved to another product is not shown against it", async ({ page }) => {
  await signIn(page, "planner");
  const items = (await getJson<{ items: { sku_id: string }[] }>(page, "/api/v1/inventory")).items;
  const [a, b] = [items[0]!.sku_id, items[1]!.sku_id];
  await page.route("**/api/v1/forecasts", async (route) => {      // the first product's forecast is slow
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto(`/forecast?ws=uci-research&sku=${a}`);
  await page.getByRole("button", { name: /Run forecast/ }).click();
  await page.getByRole("button", { name: new RegExp(`^${b}`) }).click();          // moves on while A's run is in flight
  await expect(page.getByText(`${b} — history and 28-day forecast`)).toBeVisible();
  await page.waitForTimeout(2500);                                                // A's run has now returned
  await expect(page.locator("[data-run-id]")).toHaveCount(0);                     // ...and is not displayed against B
  await expect(page.getByText("Run a forecast to overlay the median and interval.")).toBeVisible();
  // B's own run shows normally and carries B's name only
  await page.unroute("**/api/v1/forecasts");
  await page.getByRole("button", { name: /Run forecast/ }).click();
  await expect(page.locator("[data-run-id]")).toHaveCount(1);
  const run = await page.locator("[data-run-id]").getAttribute("data-run-id");
  const detail = await getJson<{ sku_ids: string[] }>(page, `/api/v1/forecasts/${run}`);
  expect(detail.sku_ids).toEqual([b]);
});

test("moving the decision clock after a run stops the run being drawn or scored", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/forecast?ws=uci-research");
  await page.getByRole("button", { name: /Run forecast/ }).click();
  await expect(page.locator("[data-run-id]")).toHaveCount(1);
  await expect(page.getByText(/This run was made from/)).toHaveCount(0);
  await page.getByLabel("Knowledge cutoff (UTC)").fill("2011-10-01T12:00");
  await expect(page.getByText(/This run was made from .* but the decision clock now reads/)).toBeVisible();
  await expect(page.getByText(/of actual days fell inside/)).toHaveCount(0);       // no score from a run of another origin
  await page.getByRole("button", { name: /Run forecast/ }).click();                // a run for the new origin is clean again
  await expect(page.getByText(/This run was made from/)).toHaveCount(0);
});

test("a selection made in one view is the selection in every other view", async ({ page }) => {
  await signIn(page, "viewer");
  const items = (await getJson<{ items: { sku_id: string }[] }>(page, "/api/v1/inventory")).items;
  const sku = items[3]!.sku_id;
  await page.goto("/inventory?ws=uci-research");
  await page.getByRole("tab", { name: "2D floor plan" }).click();
  await page.locator("tbody tr", { hasText: sku }).first().click();
  await expect(page).toHaveURL(new RegExp(`sku=${sku}`));
  await expect(page.getByRole("button", { name: new RegExp(`^${sku},`) })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#detail-title")).toContainText(sku);
  await page.getByRole("link", { name: "Forecast this product" }).click();            // same selection in the next view
  await expect(page.getByText(`${sku} — history and 28-day forecast`)).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(`^${sku}`) })).toHaveAttribute("aria-current", "true");
});

test("the action drawer and its evidence describe the same version of the same plan", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "approver");
  const api = await getJson<{ payload_hash: string; row_version: number; payload: { decision: { plan_input_hash: string } };
    evidence: { plan: { input_hash: string } } }>(page, `/api/v1/actions/${id}`, "demo");
  expect(api.evidence.plan.input_hash).toBe(api.payload.decision.plan_input_hash);
  await page.goto(`/approvals?ws=demo&action=${id}`);
  await expect(page.getByText(`Payload hash ${api.payload_hash.slice(0, 20)}… · row version ${api.row_version}`)).toBeVisible();
  await expect(page.getByText(api.evidence.plan.input_hash.slice(0, 16)).first()).toBeVisible();
});

test("starting a second investigation replaces the first one's timeline instead of mixing them", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/runs?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/run=/);
  const first = new URL(page.url()).searchParams.get("run");
  await expect(page.locator("ol[aria-label='Run stages'] li", { hasText: "done" })).toHaveCount(6, { timeout: 20_000 });
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).not.toHaveURL(new RegExp(`run=${first}`));
  await expect(page.locator("ol[aria-label='Run stages'] li", { hasText: "done" })).toHaveCount(6, { timeout: 20_000 });
  const second = new URL(page.url()).searchParams.get("run")!;
  const events = await getJson<{ seq: number; node: string; kind: string }[]>(page, `/api/v1/agent-runs/${second}/events`, "demo");
  const shown = await page.locator("ol[aria-live=polite] li").count();
  expect(shown).toBe(events.length);                                                  // exactly this run's events, once each
  expect(new Set(events.map((e) => e.seq)).size).toBe(events.length);
});
