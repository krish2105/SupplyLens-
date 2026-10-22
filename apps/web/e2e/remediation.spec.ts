import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// Session-4 remediation journeys in the running app (docs/remediation/REGISTER.md).

test("welcome art appears on sign-in only, never above a populated work queue", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome to SupplyLens" })).toBeVisible();
  await expect(page.locator('img[data-illustration="welcome"]')).toHaveAttribute("alt", "");
  await signIn(page, "planner");
  await page.goto("/?ws=uci-research");
  await expect(page.getByText(/Investigate exceptions/).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('img[data-illustration="welcome"]')).toHaveCount(0);
});

test("F03: a control that does not apply to the basis is disabled and says why", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/scenarios?ws=uci-research");
  const safety = page.getByRole("slider", { name: "Safety buffer" });
  await expect(safety).toBeDisabled();
  await expect(page.getByText(/Not applicable under lead-time demand/)).toBeVisible();
  await page.getByRole("radio", { name: /Median \+ safety days/ }).check();
  await expect(safety).toBeEnabled();
  await expect(page.getByRole("slider", { name: "Service level" })).toBeDisabled();
});

test("S22: an HTML gateway error is reported with its status, not as a parse failure", async ({ page }) => {
  await signIn(page, "planner");
  await page.route("**/api/v1/overview", (r) => r.fulfill({ status: 502, contentType: "text/html", body: "<html><body>Bad gateway</body></html>" }));
  await page.goto("/?ws=uci-research");
  const alert = page.getByRole("alert").filter({ hasText: "HTTP 502" }).first();
  await expect(alert).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/SyntaxError|Unexpected token/)).toHaveCount(0);
});

test("S18: an administrator uploads, maps and validates a CSV; bad rows are quarantined with reasons", async ({ page }) => {
  await signIn(page, "tenant_admin");
  await page.goto("/data?ws=uci-research");
  await expect(page.getByRole("heading", { name: "Onboard data" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("radio", { name: /^stock/i }).check();
  await page.getByPlaceholder(/Export from our own ERP/).fill("e2e test export, internal use");
  const stamp = Date.now();
  const csv = `as_of,location_id,sku_id,on_hand,allocated,on_order,capacity\n2030-01-01,E2E-${stamp},SKU-A,5,0,0,\n2030-01-01,E2E-${stamp},SKU-B,minus,0,0,\n`;
  await page.locator('input[type="file"]').setInputFiles({ name: `stock-${stamp}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page.getByRole("combobox", { name: "File column for on_hand" })).toHaveValue("on_hand");
  await page.getByRole("button", { name: /Validate 2 rows/ }).click();
  await expect(page.getByText("1 valid", { exact: true })).toBeVisible();
  await expect(page.getByText(/row 3.*on_hand: must be a whole number/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish snapshot" })).toBeVisible();   // not published by this test
});
