import type { Page } from "@playwright/test";
import { createDraft, expectReconciled, getJson, onboardWorkspace, runInvestigation, signIn } from "./helpers";
import { expect, test } from "./fixtures";

// Phase 4: user journeys end to end, with their critical negative paths. Each test names the journey it covers
// (docs/agent-handoff/phases/PHASE-04.md maps them).

const DEMO = { "X-SupplyLens-Tenant": "demo", "X-Requested-With": "supplylens" };
type Action = { id: string; status: string; payload_hash: string; row_version: number };

async function action(page: Page, id: string) {
  return getJson<Action>(page, `/api/v1/actions/${id}`, "demo");
}

// ------------------------------------------------------------------------------------- 1. sign-in, sessions, roles
test("J1 sign-out ends the session: the app returns to sign-in and the old session no longer opens it", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=uci-research");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect((await page.request.get("/api/v1/me")).status()).toBe(401);
  await page.goto("/approvals?ws=uci-research");
  await expect(page).toHaveURL(/\/login\?next=%2Fapprovals/);
});

test("J1 a session that ends mid-use goes to sign-in and comes back to the same screen", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/exceptions?ws=uci-research");
  await expect(page.getByRole("heading", { name: /What needs a decision/ })).toBeVisible();
  await page.request.post("/api/v1/auth/logout", { headers: { "X-Requested-With": "supplylens" } });   // e.g. another tab
  // The next request this screen makes is refused (401): switching workspace makes one at once. A background refresh may
  // already have got there first; either way the user lands on sign-in with this screen as the way back.
  await page.getByLabel("Workspace").selectOption("demo", { timeout: 3_000 }).catch(() => {});
  await expect(page).toHaveURL(/\/login\?next=%2Fexceptions/);
  await page.getByRole("button", { name: /Dev Viewer/ }).click();
  await expect(page).toHaveURL(/\/exceptions\?ws=/);
  await expect(page.getByRole("heading", { name: /What needs a decision/ })).toBeVisible();
});

test("J1 roles shape what is offered: a viewer can read a draft but not approve it, and the server refuses anyway", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "viewer");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  await expect(page.getByText(/Purchase-order draft/)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  const a = await action(page, id);
  const r = await page.request.post(`/api/v1/actions/${id}/approve`, { headers: { ...DEMO, "Idempotency-Key": crypto.randomUUID() },
    data: { payload_hash: a.payload_hash, expected_row_version: a.row_version } });
  expect(r.status()).toBe(403);
  await page.goto("/forecast?ws=uci-research");
  await expect(page.getByRole("button", { name: /Run forecast/ })).toBeDisabled();
});

// ------------------------------------------------------------------------------------- 2. workspaces and administration
test("J2 a link to a workspace the user does not belong to opens one of theirs instead of failing", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=no-such-workspace");
  const me = await (await page.request.get("/api/v1/me")).json() as { memberships: { slug: string }[] };
  await expect(page).toHaveURL(new RegExp(`ws=(${me.memberships.map((m) => m.slug).join("|")})`));
  await expect(page.getByRole("heading", { name: "Stock positions by product" })).toBeVisible();
  await expect(page.getByText(/unknown workspace/)).toHaveCount(0);
});

test("J2 an account without any workspace is told so and can sign out", async ({ page }) => {
  await signIn(page, "viewer");
  await page.route("**/api/v1/me", async (route) => {
    const res = await route.fetch();
    return route.fulfill({ response: res, json: { ...(await res.json()), memberships: [] } });
  });
  await page.goto("/");
  await expect(page.getByTestId("no-workspace")).toContainText("not a member of any workspace");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("J2 an administrator changes a member's role, the member sees it at once, and the change is audited", async ({ page }) => {
  const ws = "contract-research";
  await signIn(page, "tenant_admin");
  await page.goto(`/admin?ws=${ws}`);
  const form = page.locator("form").filter({ hasText: "Add or change a member" });
  await form.getByLabel(/Add or change a member/).fill("approver2@dev.supplylens.local");
  await form.getByLabel("Role").selectOption("viewer");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("li").filter({ hasText: "approver2@dev.supplylens.local" }).getByText("viewer", { exact: true })).toBeVisible();
  try {
    const audit = await getJson<{ action: string }[]>(page, "/api/v1/audit?limit=20", ws);
    expect(audit.some((e) => e.action.startsWith("membership"))).toBe(true);
  } finally {                                      // restore the shared fixture whatever happened
    const r = await page.request.post("/api/v1/admin/members", { headers: { "X-SupplyLens-Tenant": ws, "X-Requested-With": "supplylens",
      "Idempotency-Key": crypto.randomUUID() }, data: { email: "approver2@dev.supplylens.local", role: "approver" } });
    expect(r.ok()).toBe(true);
  }
});

test("J2 a failed administration request shows an error with retry, not an endless spinner, and retry recovers", async ({ page }) => {
  await signIn(page, "tenant_admin");
  let fail = true;
  await page.route("**/api/v1/admin/members*", (route) => fail
    ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ code: "server_error", message: "The server hit an unexpected error.", reference: "e2e00000000001" }) })
    : route.continue());
  await page.goto("/admin?ws=uci-research");
  const err = page.getByTestId("query-error").filter({ hasText: "Could not load members." });
  await expect(err).toBeVisible({ timeout: 15_000 });
  fail = false;
  await err.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator("li").filter({ hasText: "viewer@dev.supplylens.local" })).toBeVisible();
});

test("J2 a double-clicked export request creates one export", async ({ page }) => {
  await signIn(page, "tenant_admin");
  const before = (await getJson<unknown[]>(page, "/api/v1/admin/exports", "uci-research")).length;
  await page.goto("/admin?ws=uci-research");
  await page.getByRole("button", { name: "Request export" }).dblclick();
  await expect.poll(async () => (await getJson<unknown[]>(page, "/api/v1/admin/exports", "uci-research")).length, { timeout: 15_000 }).toBe(before + 1);
  // and stays one: a second request with the same intent key would have been replayed, not executed
  await page.waitForLoadState("networkidle");
  expect((await getJson<unknown[]>(page, "/api/v1/admin/exports", "uci-research")).length).toBe(before + 1);
});

// ------------------------------------------------------------------------------------- 4. documents and contract history
test("J4 an administrator adds a policy and an amendment; history, comparison and the in-force citation follow", async ({ page }) => {
  const stamp = Date.now();
  const v1 = `# Pallet labelling policy ${stamp}\nAll pallets carry one label per side.\n\nSection 2 Label stock\nLabels are thermal grade ${stamp}.\n`;
  const v2 = v1.replace("one label per side", "two labels per side");
  await signIn(page, "tenant_admin");
  await page.goto("/policies?ws=demo");
  const add = page.getByRole("region", { name: /Add a document or a new version/ });
  await add.getByLabel("Title").fill(`Pallet labelling policy ${stamp}`);
  await add.getByLabel("Type").selectOption("policy");
  await add.getByLabel("In force from").fill("2026-11-01");
  await add.getByLabel("Text file").setInputFiles({ name: "pallet-labelling.txt", mimeType: "text/plain", buffer: Buffer.from(v1) });
  await add.getByRole("button", { name: "Add document" }).click();
  await expect(page.getByTestId("document-added")).toContainText("passages");
  const amends = add.getByLabel(/Amends an existing version/);
  const option = amends.locator("option", { hasText: `Pallet labelling policy ${stamp} — v1` });
  await expect(option).toHaveCount(1);
  await amends.selectOption((await option.getAttribute("value"))!);
  await expect(add.getByLabel("Title")).toBeDisabled();                    // an amendment keeps its document's title
  await add.getByLabel("Version label").fill("v2");
  await add.getByLabel("In force from").fill("2026-12-01");
  await add.getByLabel("Text file").setInputFiles({ name: "pallet-labelling-v2.txt", mimeType: "text/plain", buffer: Buffer.from(v2) });
  await add.getByRole("button", { name: "Add amendment" }).click();
  await expect(page.getByTestId("document-added")).toBeVisible();
  const entry = page.locator("li").filter({ hasText: `Pallet labelling policy ${stamp}` }).first();
  await expect(entry.getByRole("button", { name: "v1" })).toBeVisible();
  await expect(entry.getByRole("button", { name: "v2" })).toBeVisible();
  await entry.getByRole("button", { name: "Compare versions" }).click();
  await expect(page.getByText("Side-by-side amendment")).toBeVisible();
  const hits = await getJson<{ results: { version_label: string; title: string }[] }>(page,
    `/api/v1/evidence/search?q=${encodeURIComponent(`pallet labels per side ${stamp}`)}&effective_date=2026-12-15`, "demo");
  expect(hits.results[0]).toMatchObject({ version_label: "v2", title: `Pallet labelling policy ${stamp}` });
});

test("J4 expert clause labels highlight their clause and step through occurrences", async ({ page }) => {
  await signIn(page, "viewer");
  const docs = await getJson<{ version_id: string; version_label: string }[]>(page, "/api/v1/documents", "demo");
  const version = docs[0]!.version_id;
  const text = (await getJson<{ text: string }>(page, `/api/v1/documents/versions/${version}`, "demo")).text;
  const a = text.indexOf(text.trim().split(/\s+/)[0]!);
  await page.route(`**/api/v1/documents/versions/${version}/labels`, (route) => route.fulfill({ json: [
    { category: "Minimum Commitment", char_start: a, char_end: a + 10, text: text.slice(a, a + 10), source: "CUAD v1" },
    { category: "Minimum Commitment", char_start: a + 12, char_end: a + 20, text: text.slice(a + 12, a + 20), source: "CUAD v1" },
    { category: "Parties", char_start: 0, char_end: 5, text: text.slice(0, 5), source: "CUAD v1" }] }));
  await page.goto("/policies?ws=demo");
  await page.getByRole("button", { name: docs[0]!.version_label }).first().click();
  const labels = page.getByTestId("clause-labels");
  await expect(labels).toContainText("3 from CUAD v1");
  await expect(labels.getByRole("button", { name: /Parties/ })).toHaveCount(0);         // bookkeeping, not a clause
  const btn = labels.getByRole("button", { name: /Minimum Commitment/ });
  await btn.click();
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  await expect(btn).toContainText("1/2");
  await expect(page.locator("pre mark")).toHaveText(text.slice(a, a + 10));
  await btn.click();
  await expect(btn).toContainText("2/2");
  await expect(page.locator("pre mark")).toHaveText(text.slice(a + 12, a + 20));
});

// ------------------------------------------------------------------------------------- 6-8. risk, scenarios, evidence
test("J6 the exceptions view ranks shortages, filters by type with the keyboard, and opens one in inventory", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/exceptions?ws=uci-research");
  const tabs = page.getByRole("tablist", { name: "Exception type" });
  const all = tabs.getByRole("tab", { name: /^All/ });
  await expect(all).toHaveAttribute("aria-selected", "true");
  await expect(tabs.getByRole("tab", { name: /Shortage risk/ })).toBeVisible();     // the type tabs arrive with the data
  // Under heavy parallel load focus was occasionally lost right after load (cause unverified, PHASE-04 §6): act once loaded.
  await page.waitForLoadState("networkidle");
  await all.focus();
  await expect(all).toBeFocused();
  await page.keyboard.press("ArrowRight");
  const second = tabs.getByRole("tab").nth(1);
  await expect(second).toHaveAttribute("aria-selected", "true");
  await expect(second).toBeFocused();
  await tabs.getByRole("tab", { name: /Shortage risk/ }).click();
  const first = page.getByRole("tabpanel").getByRole("article").first();
  await expect(first).toContainText(/covers .* days/);
  await expect(first).toContainText(/available at /);
  await first.getByRole("link", { name: /^Inspect/ }).click();
  await expect(page).toHaveURL(/\/inventory\?.*sku=/);
  await expect(page.locator("#detail-title")).toBeVisible();
});

test("J7 a planner computes a baseline and a draft scenario and sees them compared with plan lines", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/scenarios?ws=uci-research");
  await page.getByRole("button", { name: "Compute baseline" }).click();
  await page.getByRole("button", { name: "Compute draft" }).click();
  const table = page.getByRole("table", { name: "Scenario metrics compared" });
  await expect(table.getByRole("row").filter({ hasText: "Plan status" })).toContainText(/OPTIMAL|FEASIBLE|INFEASIBLE/, { timeout: 30_000 });
  await expect(page.getByText("Draft plan lines (not sent anywhere)")).toBeVisible();
});

test("J8 evidence search cites the clause in force and opens it highlighted", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/policies?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
  await page.getByRole("button", { name: "Search evidence" }).click();
  const result = page.getByRole("button", { name: "Open at passage" }).first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();
  await expect(page.locator("pre mark")).toBeVisible();
});

// ------------------------------------------------------------------------------------- 9. approvals: reject, stale, duplicates
test("J9 an approver rejects a draft with a reason; it leaves the queue and the reason is on record", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  await expect(page.getByRole("button", { name: "Reject" })).toBeDisabled();          // a reason is required first
  await page.getByLabel("Reason for rejection").fill("e2e: supplier B is on hold");
  await page.getByRole("button", { name: "Reject" }).click();
  await expect.poll(async () => (await action(page, id)).status).toBe("REJECTED");
  await expect(page.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  const audit = await getJson<{ action: string; entity_id: string }[]>(page, "/api/v1/audit?limit=30", "demo");
  expect(audit.some((e) => e.action === "action.rejected" && e.entity_id === id)).toBe(true);
});

test("J9 a draft edited after the approver opened it cannot be approved as displayed (stale approval)", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  const approve = page.getByRole("button", { name: /^Approve/ });
  await expect(approve).toBeEnabled();
  const before = await action(page, id);
  // The approver's screen keeps showing the version it loaded (its periodic refresh is held back here), while the
  // planner edits the draft from another session.
  await page.route(`**/api/v1/actions/${id}`, (route) => route.request().method() === "GET" ? route.fulfill({ json: before }) : route.continue());
  const planner = await page.context().browser()!.newContext({ baseURL: new URL(page.url()).origin });
  await planner.request.post("/api/v1/auth/dev-login", { headers: { "X-Requested-With": "supplylens" }, data: { email: "planner@dev.supplylens.local" } });
  const edited = await planner.request.post(`/api/v1/actions/${id}/edit`, { headers: { ...DEMO, "Idempotency-Key": crypto.randomUUID() },
    data: { quantities: { "DEMO-REF-SKU": 25 }, expected_row_version: before.row_version } });
  expect(edited.ok(), await edited.text()).toBe(true);
  await planner.close();
  await approve.click();
  await expect(page.getByRole("alert").filter({ hasText: /changed since it was displayed|does not match the current payload/ })).toBeVisible();
  await page.unroute(`**/api/v1/actions/${id}`);
  const after = await action(page, id);
  expect(after.status).toBe("PENDING_APPROVAL");                                 // nothing was approved
  expect(after.payload_hash).not.toBe(before.payload_hash);
});

test("J9 a double-clicked approval approves once and sends one order", async ({ page }) => {
  const id = await createDraft(page);
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  await page.getByRole("button", { name: /^Approve/ }).dblclick();
  await expectReconciled(page, id);
  const audit = await getJson<{ action: string; entity_id: string }[]>(page, "/api/v1/audit?limit=60", "demo");
  expect(audit.filter((e) => e.action === "action.approved" && e.entity_id === id)).toHaveLength(1);
  const { outbox } = await getJson<{ outbox: { operation_id: string } }>(page, `/api/v1/actions/${id}`, "demo");
  const orders = await getJson<{ idempotency_key: string }[]>(page, "/api/v1/sandbox/orders", "demo");
  expect(orders.filter((o) => o.idempotency_key === outbox.operation_id)).toHaveLength(1);
});

// ------------------------------------------------------------------------------------- 10-11. order, receipts, replanning
test("J11 a partial delivery shows as partial, and replanning counts the open order instead of ordering again", async ({ page }) => {
  // Its own workspace: receipts add stock for good, so this journey must never touch the shared Demo reference case.
  const { slug, asOf } = await onboardWorkspace(page);
  const run = { sku_ids: ["SKU-1"], knowledge_cutoff: `${asOf}T23:59:00Z`, effective_date: asOf, budget_minor: 500000, currency: "GBP" };
  await signIn(page, "planner");
  const [id] = await runInvestigation(page, slug, run);
  expect(id, "the investigation should prepare a draft for SKU-1").toBeTruthy();
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=${slug}&action=${id}`);
  await page.getByRole("button", { name: /^Approve/ }).click();
  await expect.poll(async () => (await getJson<{ status: string }>(page, `/api/v1/actions/${id}`, slug)).status, { timeout: 30_000 }).toBe("RECONCILED");
  // replanning while the order is open: the need is covered, so no second order is prepared
  await signIn(page, "planner");
  expect(await runInvestigation(page, slug, run)).toHaveLength(0);
  // a partial delivery
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=${slug}&action=${id}`);
  const line = page.locator("tr").filter({ hasText: "SKU-1" }).filter({ has: page.getByLabel(/Units received for SKU-1/) });
  const ordered = Number((await line.locator("td").nth(1).textContent())!.replace(/\D/g, ""));
  await page.getByLabel(/Units received for SKU-1/).fill("10");
  await page.getByRole("button", { name: "Book" }).click();
  const booked = page.locator("tr").filter({ hasText: "SKU-1" }).filter({ hasText: "PARTIAL" });
  await expect(booked).toBeVisible();
  await expect(booked.locator("td").nth(3)).toHaveText(String(ordered - 10));           // open units
  // and replanning still orders nothing: 10 received plus the rest still open cover the same need
  await signIn(page, "planner");
  expect(await runInvestigation(page, slug, run)).toHaveLength(0);
});

// ------------------------------------------------------------------------------------- 12. reporting, filters, recovery
test("J12 inventory filters, search and sorting narrow the table and say so", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=uci-research");
  const count = page.getByText(/\d+ of \d+ products/);
  await expect(count).toBeVisible();
  const total = Number((await count.textContent())!.match(/of (\d+)/)![1]);
  // The 2D floor plan's tiles also mention health ("healthy", "shortage risk"): with it on screen (as on browsers without
  // WebGL) the filter must still be found by its own name.
  await page.getByRole("tab", { name: "2D floor plan" }).click();
  await page.getByRole("combobox", { name: /^Health/ }).selectOption("shortage_risk");
  await expect(count).not.toHaveText(`${total} of ${total} products`);
  await page.getByRole("combobox", { name: /^Health/ }).selectOption("all");
  const firstSku = (await page.locator("tbody tr").first().locator(".num").first().textContent())!.trim();
  await page.getByPlaceholder(/Search code or description/).fill(firstSku);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  const header = page.getByRole("columnheader", { name: /Available/ });
  await header.getByRole("button").click();
  await expect(header).toHaveAttribute("aria-sort", /ascending|descending/);
});

test("J12 a screen that fails to render shows an error inside the app, and the rest of the app keeps working", async ({ page }) => {
  await signIn(page, "viewer");
  // A response that breaks the API contract (an object where a list belongs) crashes the overview's render. Only the
  // overview reads it among these screens, so the shell (navigation, clock) and the next screen are not involved.
  await page.route("**/api/v1/agent-runs", (route) => route.fulfill({ json: { length: 1 } }));
  await page.goto("/?ws=demo");
  await expect(page.getByTestId("render-error")).toContainText("This screen could not be displayed");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await page.unroute("**/api/v1/agent-runs");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Inventory" }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
});

test("J12 an unknown address shows a page that says so and links back", async ({ page }) => {
  await signIn(page, "viewer");
  const r = await page.goto("/no-such-page");
  expect(r?.status()).toBe(404);
  await expect(page.getByTestId("not-found")).toContainText("There is no page at this address");
  await page.getByRole("link", { name: "Go to the overview" }).click();
  await expect(page).toHaveURL(/\/(\?|$)/);
});
