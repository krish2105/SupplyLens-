import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

// UX-010 (automated part): semantic structure and keyboard behaviour that a screen reader relies on, checked on every
// screen, and each screen's accessibility tree saved for the manual assistive-technology pass
// (docs/acceptance/screen-reader-checklist.md). This does NOT replace testing with a real screen reader.

const SCREENS = ["/", "/exceptions", "/inventory", "/forecast", "/scenarios", "/runs", "/approvals", "/policies", "/research", "/value", "/data", "/admin", "/settings"];
const TREES = path.resolve(process.cwd(), "../../artifacts/reports/a11y-tree");

async function open(page: Page, p: string) {
  await signIn(page, "tenant_admin");           // tenant_admin can open every screen including Administration
  await page.goto(`${p}?ws=uci-research`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("main")).toBeVisible();
}

for (const p of SCREENS) {
  test(`structure and names: ${p}`, async ({ page }, info) => {
    await open(page, p);
    // landmarks: one main, one primary navigation, a skip link first in tab order
    await expect(page.getByRole("main")).toHaveCount(1);
    // The sidebar ("Primary") is desktop-only; below the lg breakpoint the page exposes the "Sections" strip instead.
    await expect(page.getByRole("navigation", { name: info.project.name === "desktop" ? "Primary" : "Sections" })).toHaveCount(1);
    // exactly one h1, and heading levels never jump down by more than one
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    const levels = await page.evaluate(() => [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter((h) => (h as HTMLElement).offsetParent !== null).map((h) => Number(h.tagName[1])));
    const jumps = levels.filter((l, i) => i > 0 && l - levels[i - 1]! > 1);
    expect(jumps, `heading levels skip on ${p}: ${levels.join(",")}`).toEqual([]);
    // every visible form control has an accessible name
    const unnamed = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("input:not([type=hidden]),select,textarea")]
      .filter((e) => e.offsetParent !== null && !(e as HTMLInputElement).labels?.length && !e.getAttribute("aria-label") && !e.getAttribute("aria-labelledby") && !e.title)
      .map((e) => e.outerHTML.slice(0, 90)));
    expect(unnamed, "form controls without an accessible name").toEqual([]);
    // tables are titled; images and canvases are named or hidden from assistive technology
    const untitledTables = await page.evaluate(() => [...document.querySelectorAll<HTMLTableElement>("table")]
      .filter((t) => t.offsetParent !== null && !t.caption && !t.getAttribute("aria-label") && !t.getAttribute("aria-labelledby")).length);
    expect(untitledTables, "tables without a caption or name").toBe(0);
    const unnamedMedia = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("img,canvas,[role=img]")]
      .filter((e) => e.offsetParent !== null && e.getAttribute("aria-hidden") !== "true" && !e.getAttribute("alt") && !e.getAttribute("aria-label") && !e.closest("[role=img][aria-label]")).length);
    expect(unnamedMedia, "images/canvases without a text alternative").toBe(0);
    // live regions exist for asynchronous status (connection banner at minimum)
    await expect(page.getByTestId("connection-status")).toHaveCount(1);
    // save the accessibility tree for the manual pass
    if (info.project.name === "desktop") {
      fs.mkdirSync(TREES, { recursive: true });
      fs.writeFileSync(path.join(TREES, `${p === "/" ? "overview" : p.slice(1)}.yml`), await page.locator("body").ariaSnapshot());
    }
  });
}

test("keyboard: skip link is first, reaches main, and every tab stop shows a visible focus indicator", async ({ page }) => {
  await open(page, "/exceptions");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(() => location.hash)).toBe("#main");
  // walk the first 30 tab stops from the top of the page
  await page.goto("/exceptions?ws=uci-research");
  await page.waitForLoadState("networkidle");
  const hidden: string[] = [];
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    const r = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      // Date/time inputs hand focus to native inner parts (segments, calendar button) that draw the browser's own focus ring.
      if (el instanceof HTMLInputElement && /^(date|datetime-local|time|month|week)$/.test(el.type)) return null;
      const cs = getComputedStyle(el);
      const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
      const shadow = cs.boxShadow !== "none";
      const rect = el.getBoundingClientRect();
      const visible = rect.width > 0 && rect.height > 0;
      return { name: (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40), focusVisible: el.matches(":focus-visible"), indicated: outline || shadow, visible };
    });
    if (r && r.visible && (!r.focusVisible || !r.indicated)) hidden.push(r.name);
  }
  expect(hidden, "focused controls with no visible focus indicator").toEqual([]);
});

test("keyboard: command palette opens with Ctrl+K, traps focus, closes with Escape and returns focus", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "the palette button is hidden below the md breakpoint; it is a keyboard accelerator");
  await open(page, "/exceptions");
  const trigger = page.getByRole("button", { name: "Open command palette" });
  await trigger.focus();
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Search pages, products and commands" })).toBeFocused();
  for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");           // focus must stay inside the dialog
  expect(await page.evaluate(() => !!document.activeElement?.closest("[role=dialog]"))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("keyboard: the approval decision can be made without a mouse", async ({ page }) => {
  const { createDraft } = await import("./helpers");
  const id = await createDraft(page);
  await signIn(page, "approver");
  await page.goto(`/approvals?ws=demo&action=${id}`);
  const approve = page.getByRole("button", { name: /^Approve/ });
  await approve.focus();
  await expect(approve).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("RECONCILED").first()).toBeVisible({ timeout: 20_000 });
});

test("status changes are announced: run progress and errors use live regions or alerts", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/runs?ws=demo&known=2026-10-20T09:00:00.000Z&eff=2026-10-20");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.locator("ol[aria-live=polite]")).toHaveCount(1);                       // the event timeline
  await expect(page.locator("ol[aria-label='Run stages'] li", { hasText: "done" })).toHaveCount(6, { timeout: 20_000 });
  await page.route("**/api/v1/overview", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"code":"boom","message":"overview failed"}' }));
  await page.goto("/?ws=uci-research");
  await expect(page.getByRole("alert").filter({ hasText: "overview failed" })).toBeVisible({ timeout: 15_000 });
});

test("reduced motion and zoom: no horizontal scroll at 200% zoom equivalent width", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 640, height: 800 });                                 // 1280 CSS px at 200% zoom
  await open(page, "/inventory");
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw).toBeLessThanOrEqual(iw + 1);
});
