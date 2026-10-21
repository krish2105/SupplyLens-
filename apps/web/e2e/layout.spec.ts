import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

for (const path of ["/", "/inventory", "/approvals", "/policies", "/data", "/exceptions", "/research", "/value", "/forecast", "/runs", "/scenarios"]) {
  test(`no horizontal scroll and no serious axe violations: ${path}`, async ({ page }, info) => {
    await signIn(page, "planner");
    await page.goto(`${path}?ws=uci-research`);
    await page.waitForLoadState("networkidle");
    const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(sw).toBeLessThanOrEqual(iw + 1);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).exclude("canvas").analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    await info.attach("axe", { body: JSON.stringify(results.violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length })), null, 2), contentType: "application/json" });
    expect(serious.map((v) => `${v.id} (${v.nodes.length})`)).toEqual([]);
  });
}

for (const [ws, path, role] of [["contract-research", "/market", "viewer"], ["contract-research", "/", "viewer"], ["uci-research", "/admin", "tenant_admin"]] as const) {
  test(`axe and overflow: ${ws} ${path}`, async ({ page }) => {
    await signIn(page, role);
    await page.goto(`${path}?ws=${ws}`);
    await page.waitForLoadState("networkidle");
    const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(sw).toBeLessThanOrEqual(iw + 1);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).exclude("canvas").analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id} (${v.nodes.length})`)).toEqual([]);
  });
}

test("dark theme has no serious contrast violations on key screens", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("supplylens-theme", "dark"));
  await signIn(page, "planner");
  for (const path of ["/", "/exceptions", "/research", "/approvals"]) {
    await page.goto(`${path}?ws=uci-research`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveClass(/dark/);
    const r = await new AxeBuilder({ page }).withTags(["wcag2aa"]).exclude("canvas").analyze();
    expect(r.violations.filter((v) => v.id === "color-contrast").map((v) => `${path}: ${v.nodes.length}`)).toEqual([]);
  }
});
