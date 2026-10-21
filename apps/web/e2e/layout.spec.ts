import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

for (const path of ["/", "/inventory", "/approvals", "/policies", "/data"]) {
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
