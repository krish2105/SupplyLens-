// Phase 4B: the visual and UX defects found in the screen audit (docs/agent-handoff/phases/PHASE-04B.md), each pinned by
// the behaviour that was wrong. Runs on the desktop and Pixel 7 projects; phone-only checks skip at desktop width.
import { expect, test } from "./fixtures";
import { getJson, signIn } from "./helpers";

const phone = (w: number | undefined) => (w ?? 1440) < 768;

test("phone: the sections menu names the current section, navigates within the workspace and closes", async ({ page }) => {
  test.skip(!phone(page.viewportSize()?.width), "the menu replaces the sidebar below lg; checked at phone width");
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=uci-research");
  const trigger = page.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /current: Inventory/ });
  await trigger.click();
  const menu = page.getByRole("dialog", { name: "Sections" });
  await expect(menu.getByRole("link", { name: "Inventory" })).toHaveAttribute("aria-current", "page");
  // every section is reachable (before: a clipped strip with no current indicator)
  for (const name of ["Overview", "Approvals", "Policies & evidence", "Research", "Settings"]) await expect(menu.getByRole("link", { name })).toBeVisible();
  await menu.getByRole("link", { name: "Forecast lab" }).click();
  await expect(page).toHaveURL(/\/forecast\?.*ws=uci-research/);
  await expect(menu).toBeHidden();
  // keyboard: Escape closes and returns focus to the trigger
  const again = page.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /current: Forecast lab/ });
  await again.click();
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(again).toBeFocused();
});

test("phone: the header scrolls away instead of covering a third of the screen", async ({ page }) => {
  test.skip(!phone(page.viewportSize()?.width), "the header stays sticky from tablet width up");
  await signIn(page, "planner");
  await page.goto("/exceptions?ws=uci-research");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.mouse.wheel(0, 900);
  await expect.poll(async () => (await page.getByLabel("Workspace").boundingBox())?.y ?? 0).toBeLessThan(0);
});

test("sign-in fits the screen: no horizontal scroll and every account is fully visible", async ({ page }) => {
  await page.goto("/login");
  const accounts = page.getByRole("button", { name: /Dev (Viewer|Planner|Approver|Tenant Admin)/ });
  await expect(accounts.first()).toBeVisible();
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(vw);
  for (const box of await accounts.evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [r.left, r.right]; }))) {
    expect(box[0]).toBeGreaterThanOrEqual(0);
    expect(box[1]).toBeLessThanOrEqual(vw);
  }
});

test("wide tables scroll inside a labelled region instead of widening the page", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/value?ws=uci-research");
  const region = page.getByRole("region", { name: "Value ledger items, scrollable" });
  await expect(region).toBeVisible();
  const [sw, cw] = await region.evaluate((e) => [e.scrollWidth, e.clientWidth]);
  if (phone(page.viewportSize()?.width)) expect(sw).toBeGreaterThan(cw);   // the ledger is wider than a phone: it scrolls here
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test("supplier market explains where public award data lives, per workspace", async ({ page }) => {
  await signIn(page, "viewer");
  const s = await getJson<{ available: boolean }>(page, "/api/v1/market/summary", "contract-research");
  test.skip(s.available, "this stack has World Bank awards imported; the absent-data messages do not apply");
  await page.goto("/market?ws=contract-research");
  await expect(page.getByText(/No public award data has been imported into this workspace yet/)).toBeVisible();
  // before: this workspace was told to switch to itself
  await expect(page.getByText(/Switch to it with the workspace selector/)).toHaveCount(0);
  await page.goto("/market?ws=uci-research");
  await expect(page.getByText(/Public award data lives in the Contract research workspace/)).toBeVisible();
});

test("a workspace that holds only documents says it has no operational date; a failed overview does not", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/market?ws=contract-research");
  await expect(page.getByText(/No operational date in this workspace/)).toBeVisible();
  await page.route("**/api/v1/overview", (r) => r.fulfill({ status: 500, contentType: "application/json",
    body: JSON.stringify({ code: "server_error", message: "The server hit an unexpected error.", reference: "e2e" }) }));
  await page.goto("/?ws=uci-research");
  await expect(page.getByText("The server hit an unexpected error.")).toBeVisible();
  await expect(page.getByText(/No operational date in this workspace/)).toHaveCount(0);
});

test("the overview does not call a workspace fictional, or empty, before it knows what it holds", async ({ page }) => {
  await signIn(page, "viewer");
  await page.route("**/api/v1/overview", () => new Promise(() => {}));   // held: the overview never arrives
  await page.goto("/?ws=uci-research", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("At risk")).toBeVisible();                 // the rest of the page has rendered
  await expect(page.getByText("Fictional demo workspace")).toHaveCount(0);
  await expect(page.getByText(/No sales dataset in this workspace/)).toHaveCount(0);
});

test("inventory that fails to load draws no empty warehouse and no blank snapshot", async ({ page }) => {
  await signIn(page, "viewer");
  await page.route("**/api/v1/inventory*", (r) => r.fulfill({ status: 500, contentType: "application/json",
    body: JSON.stringify({ code: "server_error", message: "The server hit an unexpected error.", reference: "e2e" }) }));
  await page.goto("/inventory?ws=uci-research");
  await expect(page.getByText("The server hit an unexpected error.").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("The layout appears once stock positions load.")).toBeVisible();
  await expect(page.getByText("No snapshot to show")).toBeVisible();
  await expect(page.locator('[aria-label^="3D schematic warehouse"] canvas')).toHaveCount(0);   // charts below draw their own
});

test("phone: opening a version comparison brings the reader into view and moves focus to it", async ({ page }) => {
  test.skip(!phone(page.viewportSize()?.width), "side by side at desktop width");
  await signIn(page, "viewer");
  await page.goto("/policies?ws=demo");
  await page.getByRole("button", { name: "Compare versions" }).first().click();
  const reader = page.getByRole("region", { name: "Document reader" });
  await expect(reader).toBeFocused();
  await expect(reader.getByText("Side-by-side amendment")).toBeInViewport();
  // the reader starts in the upper part of the screen (or as high as the page end allows), not peeking in at the bottom
  await expect.poll(() => reader.evaluate((e) => {
    const room = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
    return e.getBoundingClientRect().top <= window.innerHeight * 0.4 || room < 2;
  })).toBe(true);
});

test("illustrations match their states and every image loads", async ({ page }) => {
  await signIn(page, "viewer");
  const loaded = async () => {
    for (const img of await page.locator("img").all()) {
      if (!(await img.isVisible())) continue;
      await img.scrollIntoViewIfNeeded();
      await expect.poll(() => img.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0), { message: await img.getAttribute("src") ?? "img" }).toBe(true);
    }
  };
  await page.goto("/inventory?ws=uci-research");
  await page.getByPlaceholder("Search code or description").fill("zzz-no-such-product");
  await expect(page.locator('[data-state="empty_filtered"] [data-illustration]')).toHaveAttribute("data-illustration", "no-results");
  await loaded();
  await page.goto("/admin?ws=uci-research");                            // a viewer is not an administrator
  await expect(page.getByText("Administrators only")).toBeVisible();
  await loaded();
  await page.goto("/approvals?ws=demo");
  await page.getByRole("tab", { name: "Stale" }).click();
  await expect(page.locator('[data-state="no_pending"] [data-illustration]').or(page.getByText("Nothing in this queue"))).toBeVisible();
  await loaded();
});

test("after adding a document, focus and scroll stay with the form (the reader does not pull them away)", async ({ page }) => {
  // QA-4B-01 follow-up: a frame after an upload the reader took focus and scrolled the page up; a field the user had moved
  // to lost its typing (seen in CI as an amendment saved with the label "v1" instead of "v2")
  const stamp = `${Date.now()}${crypto.randomUUID().slice(0, 8)}`;
  await signIn(page, "tenant_admin");
  await page.goto("/policies?ws=demo");
  const add = page.getByRole("region", { name: /Add a document or a new version/ });
  await add.getByLabel("Title").fill(`Focus check ${stamp}`);
  await add.getByLabel("Type").selectOption("policy");
  await add.getByLabel("In force from").fill("2026-11-01");
  await add.getByLabel("Text file").setInputFiles({ name: "focus.txt", mimeType: "text/plain", buffer: Buffer.from(`focus check ${stamp}\n`) });
  await add.getByRole("button", { name: "Add document" }).click();
  await expect(page.getByTestId("document-added")).toBeVisible();
  const label = add.getByLabel("Version label");
  await label.focus();
  const y = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(600);                                       // several frames: any deferred focus move has run
  await expect(label).toBeFocused();
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - y)).toBeLessThan(2);
});
