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

    if (wname === "phone") test("sections menu open", async ({ page }) => {
      await open(page, theme, "/inventory", "uci-research", "viewer", "Stock positions by product");
      await page.getByRole("navigation", { name: "Sections" }).getByRole("button").click();
      await expect(page.getByRole("dialog", { name: "Sections" })).toBeVisible();
      await expect(page).toHaveScreenshot(`sections-menu-${wname}-${theme}.png`, SHOT(page));
    });
  });
}
