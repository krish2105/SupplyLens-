import { expect, test } from "@playwright/test";
import { createDraft, signIn } from "./helpers";

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

test("S15: switching workspace drops the previous workspace's selected draft instead of showing or refetching it", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  await expect(page.getByText(/Purchase-order draft/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("combobox").first().selectOption("uci-research");
  await expect(page).not.toHaveURL(/action=/);
  await expect(page.getByText("Select a draft to review")).toBeVisible();
  // Next.js keeps an empty role=alert route announcer on every page; no alert may carry an error message
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
});

test("S17: switching theme recolours a zoomed chart and keeps its zoom range", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/forecast?ws=uci-research&sku=85123A");
  const chart = page.locator("[data-chart-theme]").first();
  await expect(chart).toBeVisible({ timeout: 20_000 });
  const read = () => chart.evaluate((el) => {
    const c = (el as HTMLElement & { __chart?: { getOption(): any } }).__chart!;
    const o = c.getOption();
    return { start: o.dataZoom[0].start as number, end: o.dataZoom[0].end as number, axis: o.yAxis[0].axisLabel.color as string };
  });
  await chart.evaluate((el) => (el as any).__chart.dispatchAction({ type: "dataZoom", start: 40, end: 80 }));
  await page.getByRole("radio", { name: "Light theme" }).check();
  await expect(chart).toHaveAttribute("data-chart-theme", "light");
  const before = await read();
  await page.getByRole("radio", { name: "Dark theme" }).check();
  await expect(page.locator("[data-chart-theme]").first()).toHaveAttribute("data-chart-theme", "dark");
  await expect.poll(async () => (await read()).axis).not.toBe(before.axis);             // recoloured from the new tokens
  const after = await read();
  expect([Math.round(after.start), Math.round(after.end)]).toEqual([Math.round(before.start), Math.round(before.end)]);
  expect(Math.round(after.start)).toBe(40);
});

test("S17: the theme switch is a radio group driven by arrow keys", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/?ws=uci-research");
  const light = page.getByRole("radio", { name: "Light theme" });
  await light.check();
  await light.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Dark theme" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Dark theme" })).toBeFocused();
});

test.describe("UX-009 non-happy states", () => {
  test("denied by the server: a generic restricted message, no data", async ({ page }) => {
    await signIn(page, "planner");
    await page.route("**/api/v1/inventory?*", (r) => r.fulfill({ status: 403, contentType: "application/json", body: '{"code":"forbidden","message":"role may not"}' }));
    await page.route("**/api/v1/inventory", (r) => r.fulfill({ status: 403, contentType: "application/json", body: '{"code":"forbidden","message":"role may not"}' }));
    await page.goto("/inventory?ws=uci-research");
    await expect(page.getByText("You do not have access to this")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('img[data-illustration="restricted-access"]')).toHaveCount(1);
  });

  test("an expired session sends the user to sign-in instead of spinning", async ({ page }) => {
    await signIn(page, "planner");
    await page.route("**/api/v1/me", (r) => r.fulfill({ status: 401, contentType: "application/json", body: '{"code":"session_revoked","message":"ended"}' }));
    await page.goto("/inventory?ws=uci-research");
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });

  test("a server error shows its reference so it can be traced", async ({ page }) => {
    await signIn(page, "planner");
    await page.route("**/api/v1/overview", (r) => r.fulfill({ status: 500, contentType: "application/json",
      headers: { "x-trace-id": "abc123def456789" }, body: '{"code":"server_error","message":"The server hit an unexpected error. Your input was not lost."}' }));
    await page.goto("/?ws=uci-research");
    await expect(page.getByRole("alert").filter({ hasText: "ref abc123def456" }).first()).toBeVisible({ timeout: 15_000 });
  });

  test("no stock records for the chosen date is shown as missing data, not zero stock", async ({ page }) => {
    await signIn(page, "planner");
    await page.goto("/inventory?ws=demo&eff=2020-01-01");
    await expect(page.getByText("No inventory records in this workspace")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/not zero stock/)).toBeVisible();
  });
});

test("S22: a session check that fails for any reason other than 401 shows an error with retry, not an endless spinner", async ({ page }) => {
  await signIn(page, "planner");
  await page.route("**/api/v1/me", (r) => r.fulfill({ status: 404, contentType: "text/plain", body: "The page could not be found" }));
  await page.goto("/?ws=uci-research");
  await expect(page.getByText(/could not confirm your session/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText("Checking your session")).toHaveCount(0);
});
