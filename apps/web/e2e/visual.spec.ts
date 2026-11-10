// Screenshot regression (Phase 4B): the critical screens, light and dark, at desktop (1440×900) and phone (390×844) width.
// Its own project ("visual"): run it on a freshly seeded stack, before the other suites change data. Baselines are per
// platform (…-darwin.png locally, …-linux.png in CI) and are reviewed by eye before they are committed: a changed
// baseline is never accepted just to make the run pass. Masked: only the WebGL scene (GPU-dependent pixels); the
// ECharts canvases (data-zr-dom-id) stay in, so a chart that fails to draw fails the comparison.
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

type Role = "viewer" | "planner";
// name, path, workspace, role, text that proves the screen rendered its data
const SCREENS: [string, string, string | null, Role | null, string | RegExp][] = [
  ["login", "/login", null, null, "Welcome to SupplyLens"],
  ["overview", "/", "uci-research", "planner", /stocked products/],
  ["exceptions", "/exceptions", "uci-research", "planner", "What needs a decision"],
  ["inventory", "/inventory", "uci-research", "planner", "Stock positions by product"],
  ["forecast", "/forecast", "uci-research", "planner", "Unit-sales forecasts"],
  ["research", "/research", "uci-research", "viewer", "Measured results"],
  ["value", "/value", "uci-research", "viewer", "A value ledger"],
  ["market", "/market", "contract-research", "viewer", "Public procurement awards"],
  ["settings", "/settings", "uci-research", "viewer", "Appearance, connections and audit"],
  ["not-found", "/no-such-page", null, "viewer", "There is no page at this address"],
];

const WIDTHS = {
  desktop: { viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false },
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
} as const;

const SHOT = (page: Page) => ({ mask: [page.locator("canvas:not([data-zr-dom-id])")], maxDiffPixelRatio: 0.01 });

async function open(page: Page, theme: "light" | "dark", path: string, ws: string | null, role: Role | null, ready: string | RegExp) {
  await page.addInitScript((t) => { try { localStorage.setItem("supplylens-theme", t); } catch { /* none */ } }, theme);
  if (role) await signIn(page, role);
  await page.goto(`${path}${ws ? `?ws=${ws}` : ""}`);
  await expect(page.getByText(ready).first()).toBeVisible({ timeout: 20_000 });
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  // every chart on screen has drawn (charts are loaded lazily)
  await page.waitForFunction(() => [...document.querySelectorAll("[data-chart-theme]")].every((c) => c.querySelector("canvas")));
}

for (const [wname, ctx] of Object.entries(WIDTHS)) for (const theme of ["light", "dark"] as const) {
  test.describe(`${wname} ${theme}`, () => {
    test.use({ ...ctx, colorScheme: theme, reducedMotion: "reduce" });

    for (const [name, path, ws, role, ready] of SCREENS) {
      test(name, async ({ page }) => {
        await open(page, theme, path, ws, role, ready);
        await expect(page).toHaveScreenshot(`${name}-${wname}-${theme}.png`, SHOT(page));
      });
    }

    // Phase 8: the status assistant drawer (first use with its art; a refused change request) and Policies › Extracted
    // terms on the fictional Demo agreement. Fixed text only: an answered question shows live stock, which other suites change.
    test("status assistant", async ({ page }) => {
      await open(page, theme, "/settings", "uci-research", "viewer", "Appearance, connections and audit");
      await page.getByRole("button", { name: "Ask about an order or stock" }).click();
      const drawer = page.getByRole("dialog", { name: "Ask about an order or stock" });
      const art = drawer.locator('img[data-illustration="assistant-ready"]');
      await expect(art).toBeVisible();
      await expect.poll(() => art.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true);
      await expect(page).toHaveScreenshot(`assistant-first-${wname}-${theme}.png`, SHOT(page));
      await drawer.getByLabel("Your question").fill("cancel the order for SYN001");
      await drawer.getByRole("button", { name: "Ask", exact: true }).click();
      await expect(drawer.getByTestId("assistant-withheld")).toBeVisible({ timeout: 15_000 });
      await expect(page).toHaveScreenshot(`assistant-withheld-${wname}-${theme}.png`, SHOT(page));
    });

    test("extracted terms", async ({ page }) => {
      await open(page, theme, "/policies", "demo", "viewer", "Supplier terms, versions and citations");
      const entry = page.locator("li").filter({ hasText: "Reference Supplier A agreement" }).first();
      await entry.getByRole("button", { name: "v1", exact: true }).click();
      const reader = page.getByRole("region", { name: "Document reader" });
      await reader.getByRole("tab", { name: "Extracted terms" }).click();
      const panel = reader.getByTestId("extracted-terms");
      await expect(panel.getByRole("row").nth(1)).toBeVisible();
      await panel.scrollIntoViewIfNeeded();
      await expect(page).toHaveScreenshot(`extracted-terms-${wname}-${theme}.png`, SHOT(page));
    });

    if (wname === "phone") test("sections menu open", async ({ page }) => {
      await open(page, theme, "/inventory", "uci-research", "viewer", "Stock positions by product");
      await page.getByRole("navigation", { name: "Sections" }).getByRole("button").click();
      await expect(page.getByRole("dialog", { name: "Sections" })).toBeVisible();
      await expect(page).toHaveScreenshot(`sections-menu-${wname}-${theme}.png`, SHOT(page));
    });
  });
}

// Phase 8 F4: two critical screens after switching theme at runtime, the path that left the 3D view on the old theme
// (F1). The system scheme is the opposite of the starting theme, as on the owner's machine. The WebGL scene stays masked
// (GPU pixels; its colours are asserted in e2e/theme.spec.ts); charts and every DOM surface are compared.
const SWITCHED: [string, string, "light" | "dark", "light" | "dark", string | RegExp][] = [
  ["overview", "/", "light", "dark", /stocked products/],
  ["inventory", "/inventory", "dark", "light", "Stock positions by product"],
];
test.describe("desktop after a runtime theme switch", () => {
  test.use({ ...WIDTHS.desktop, reducedMotion: "reduce" });
  for (const [name, path, from, to, ready] of SWITCHED) {
    test(`${name} ${from} → ${to}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: to });
      await open(page, from, path, "uci-research", "planner", ready);
      await page.getByRole("radio", { name: to === "light" ? "Light theme" : "Dark theme" }).check({ force: true });
      await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${to}\\b`));
      // every chart was rebuilt from the new theme's tokens before the capture
      await expect.poll(() => page.locator("[data-chart-theme]").evaluateAll((els, t) => els.every((e) => e.getAttribute("data-chart-theme") === t), to)).toBe(true);
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await expect(page).toHaveScreenshot(`${name}-desktop-switched-${to}.png`, SHOT(page));
    });
  }
});
