// Phase 8 WP-ART: the owner's illustrations A02, A13 and A16 appear only in the state each was briefed for, never when
// real data exists, never for the wrong role, and always as decorative images (alt="", hidden from assistive tech).
// Datasets and batches are mocked where the seeded stack cannot show a state (it always has a dataset).
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { getJson, signIn } from "./helpers";

const art = (page: Page, name: string) => page.locator(`img[data-illustration="${name}"]`);

async function decorative(page: Page, name: string) {
  const img = art(page, name);
  await expect(img).toHaveCount(1);
  await expect(img).toHaveAttribute("alt", "");
  await expect(img).toHaveAttribute("aria-hidden", "true");
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
}

/** /data with no admitted dataset and the given import batches. */
async function noDataset(page: Page, batches: unknown[]) {
  await page.route("**/api/v1/datasets", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/onboarding/batches", (r) => r.fulfill({ json: batches }));
}

test.describe("A02 import data", () => {
  test("a tenant admin with nothing imported yet sees it", async ({ page }) => {
    await signIn(page, "tenant_admin");
    await noDataset(page, []);
    await page.goto("/data?ws=uci-research");
    await expect(page.getByRole("heading", { name: "No dataset admitted in this workspace" })).toBeVisible();
    await expect(page.getByText("Add your first dataset")).toBeVisible();
    await decorative(page, "import-data");
  });

  test("a viewer, who cannot import, does not", async ({ page }) => {
    await signIn(page, "viewer");
    await noDataset(page, []);
    await page.goto("/data?ws=uci-research");
    await expect(page.getByText("Add your first dataset")).toBeVisible();
    await expect(art(page, "import-data")).toHaveCount(0);
  });

  test("not once an import batch exists, and not where a dataset is admitted", async ({ page }) => {
    await signIn(page, "tenant_admin");
    await noDataset(page, [{ id: "b1", kind: "sales", file_name: "sales.csv", status: "VALIDATED", rows_valid: 10, rows_quarantined: 0,
      snapshot_sha256: null, created_at: "2026-11-10T00:00:00Z" }]);
    await page.goto("/data?ws=uci-research");
    await expect(page.getByText("Add your first dataset")).toBeVisible();
    await expect(art(page, "import-data")).toHaveCount(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.goto("/data?ws=uci-research");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("No dataset admitted in this workspace")).toHaveCount(0);
    await expect(art(page, "import-data")).toHaveCount(0);
  });

  test("not in the locked public demo, where imports are refused", async ({ page }) => {
    await signIn(page, "tenant_admin");
    await noDataset(page, []);
    await page.route("**/api/v1/auth/config", async (r) => {
      const res = await r.fetch();
      await r.fulfill({ response: res, json: { ...(await res.json()), environment: "demo" } });
    });
    await page.goto("/data?ws=uci-research");
    await expect(page.getByText("Add your first dataset")).toBeVisible();
    await expect(art(page, "import-data")).toHaveCount(0);
  });
});

test.describe("A13 empty suppliers", () => {
  test("Contract research without imported award data shows it; other workspaces do not", async ({ page }) => {
    await signIn(page, "viewer");
    const s = await getJson<{ available: boolean }>(page, "/api/v1/market/summary", "contract-research");
    test.skip(s.available, "award data is imported in this stack (the hosted demo): the empty state cannot occur");
    await page.goto("/market?ws=contract-research");
    await expect(page.getByText("No public award data has been imported into this workspace yet", { exact: false })).toBeVisible();
    await decorative(page, "empty-suppliers");
    await page.goto("/market?ws=uci-research");
    await expect(page.getByText("lives in the Contract research workspace", { exact: false })).toBeVisible();
    await expect(art(page, "empty-suppliers")).toHaveCount(0);
  });
});

test.describe("A16 empty value study", () => {
  test("shown only while the value ledger has no study", async ({ page }) => {
    await signIn(page, "viewer");
    await page.goto("/value?ws=uci-research");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(art(page, "empty-value-study")).toHaveCount(0);          // the seeded stack has a study: no art over data
    await page.route("**/api/v1/value", async (r) => {
      const res = await r.fetch();
      await r.fulfill({ response: res, json: { ...(await res.json()), ledger: [] } });
    });
    await page.reload();
    await expect(page.getByText("No simulation study yet")).toBeVisible();
    await decorative(page, "empty-value-study");
  });
});

test("errors and loading never use empty-state art", async ({ page }) => {
  await signIn(page, "tenant_admin");
  await page.route("**/api/v1/datasets", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"code":"server_error","message":"x"}' }));
  await page.goto("/data?ws=uci-research");
  await expect(page.getByRole("alert").first()).toBeVisible({ timeout: 15_000 });
  await expect(art(page, "import-data")).toHaveCount(0);
});
