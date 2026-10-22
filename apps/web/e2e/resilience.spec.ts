import { expect, test } from "@playwright/test";
import { breakWebGL, createDraft, expectReconciled, getJson, signIn } from "./helpers";

// EXE-010 / UX-009 / BUS-008: the reference workflow stays usable when WebGL fails and when the network drops.

test.describe("WebGL failure", () => {
  test("WebGL unavailable from the start: 2D floor plan, same records, selection still works", async ({ page }) => {
    await breakWebGL(page);
    await signIn(page, "viewer");
    await page.goto("/inventory?ws=uci-research");
    await expect(page.getByRole("tab", { name: "3D schematic" })).toBeDisabled();
    await expect(page.getByRole("tab", { name: "2D floor plan" })).toHaveAttribute("aria-selected", "true");
    await page.locator("tbody tr").first().click();
    await expect(page.locator("#detail-title")).toBeVisible();
    await page.goto("/?ws=uci-research");
    await expect(page.getByText(/Showing the 2D floor plan/)).toBeVisible();
  });

  test("the reference workflow completes with WebGL unavailable", async ({ page }) => {
    await breakWebGL(page);
    await signIn(page, "planner");
    await page.goto("/runs?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
    await page.getByRole("button", { name: "Start investigation" }).click();
    await expect(page).toHaveURL(/run=/);
    await expect(page.locator("ol[aria-label='Run stages'] li", { hasText: "done" })).toHaveCount(6, { timeout: 20_000 });
    const run = new URL(page.url()).searchParams.get("run")!;
    const detail = await getJson<{ actions: { id: string }[] }>(page, `/api/v1/agent-runs/${run}`, "demo");
    await signIn(page, "approver");
    await page.goto(`/approvals?ws=demo&action=${detail.actions[0]!.id}`);
    await page.getByRole("button", { name: "Approve US$180.00" }).click();
    await expectReconciled(page, detail.actions[0]!.id);
  });

  test("the renderer fails after the capability check passed: error boundary hands over to the floor plan", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await breakWebGL(page, true);
    await signIn(page, "viewer");
    await page.goto("/inventory?ws=uci-research");
    await expect(page.getByText(/The 3D view stopped working on this device/)).toBeVisible();
    await expect(page.getByRole("tab", { name: "3D schematic" })).toBeDisabled();
    await page.locator("tbody tr").first().click();                       // the rest of the page still works
    await expect(page.locator("#detail-title")).toBeVisible();
    expect(errors, "no uncaught page error escapes the boundary").toEqual([]);
  });

  test("a lost WebGL context mid-session falls back to the floor plan", async ({ page }) => {
    await signIn(page, "viewer");
    await page.goto("/inventory?ws=uci-research");
    await expect(page.locator("canvas")).toBeVisible();
    await page.evaluate(() => {
      const gl = (document.querySelector("canvas") as HTMLCanvasElement).getContext("webgl2") ?? (document.querySelector("canvas") as HTMLCanvasElement).getContext("webgl");
      (gl as WebGLRenderingContext).getExtension("WEBGL_lose_context")!.loseContext();
    });
    await expect(page.getByText(/The 3D view stopped working on this device/)).toBeVisible();
    await page.locator("tbody tr").first().click();
    await expect(page.locator("#detail-title")).toBeVisible();
  });
});

test.describe("network interruption", () => {
  test("offline is announced, typed input is kept, and recovery needs no re-entry", async ({ page, context }) => {
    const id = await createDraft(page);
    await signIn(page, "approver");
    await page.goto(`/approvals?ws=demo&action=${id}`);
    await page.getByLabel("Reason for rejection").fill("supplier quote looks stale");
    await context.setOffline(true);
    await expect(page.getByText("You are offline.")).toBeVisible();
    await page.getByRole("button", { name: /Reject/ }).click();
    await expect(page.getByText(/Waiting for connection/)).toBeVisible();        // held, not sent, not lost
    await expect(page.getByLabel("Reason for rejection")).toHaveValue("supplier quote looks stale");
    const held = await getJson<{ status: string; approvals: unknown[] }>(page, `/api/v1/actions/${id}`, "demo");
    expect(held.status).toBe("PENDING_APPROVAL");                                  // nothing reached the server while offline
    expect(held.approvals).toHaveLength(0);
    await context.setOffline(false);
    await expect(page.getByText("You are offline.")).toHaveCount(0);
    // sent automatically on reconnect; wait on THIS action, not on any "REJECTED" text elsewhere on the page
    await expect.poll(async () => (await getJson<{ status: string }>(page, `/api/v1/actions/${id}`, "demo")).status,
      { timeout: 15_000 }).toBe("REJECTED");
    const a = await getJson<{ approvals: { decision: string }[] }>(page, `/api/v1/actions/${id}`, "demo");
    expect(a.approvals.filter((x) => x.decision === "REJECTED")).toHaveLength(1);                     // exactly once
  });

  test("unsent input survives a reload", async ({ page }) => {
    const id = await createDraft(page);
    await signIn(page, "approver");
    await page.goto(`/approvals?ws=demo&action=${id}`);
    await page.getByLabel("Reason for rejection").fill("keep this across a reload");
    await page.reload();
    await expect(page.getByLabel("Reason for rejection")).toHaveValue("keep this across a reload");
  });

  test("a lost response never duplicates an approval or an order", async ({ page }) => {
    const id = await createDraft(page);
    await signIn(page, "approver");
    await page.goto(`/approvals?ws=demo&action=${id}`);
    let firstCall = true;
    await page.route("**/api/v1/actions/*/approve", async (route) => {
      if (firstCall) { firstCall = false; await route.fetch(); await route.abort("connectionreset"); }   // server processed it; reply lost
      else await route.continue();
    });
    await page.getByRole("button", { name: /^Approve/ }).click();
    await expect(page.getByText(/Connection lost/)).toBeVisible();
    await page.getByRole("button", { name: "Try again" }).click();
    // Wait on THIS action, not on any "RECONCILED" text: the page also lists other actions that are already reconciled.
    await expectReconciled(page, id);
    const a = await getJson<{ approvals: { decision: string }[] }>(page, `/api/v1/actions/${id}`, "demo");
    expect(a.approvals.filter((x) => x.decision === "APPROVED")).toHaveLength(1);
    const orders = await getJson<{ caller_ref: string }[]>(page, "/api/v1/sandbox/orders", "demo");
    expect(orders.filter((o) => o.caller_ref === id)).toHaveLength(1);
  });

  test("an investigation keeps its state through a dropped connection", async ({ page, context }) => {
    await signIn(page, "planner");
    await page.goto("/runs?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
    await page.getByRole("button", { name: "Start investigation" }).click();
    await context.setOffline(true);
    await page.waitForTimeout(2500);
    await context.setOffline(false);
    await expect(page).toHaveURL(/run=/);
    await expect(page.getByText("WAITING FOR APPROVAL").first()).toBeVisible({ timeout: 30_000 });
    const run = new URL(page.url()).searchParams.get("run")!;
    const events = await getJson<{ seq: number }[]>(page, `/api/v1/agent-runs/${run}/events`, "demo");
    await expect(page.locator("ol[aria-live=polite] li")).toHaveCount(events.length);          // nothing lost, nothing duplicated
    await expect(page.locator("ol[aria-label='Run stages'] li", { hasText: "done" })).toHaveCount(6);
  });
});
