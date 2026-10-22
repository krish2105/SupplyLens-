// Which element is the LCP, and what does the page wait for, under the throttled mobile profile? (UX-011 diagnosis)
// Usage: node scripts/lcp-probe.mjs / /forecast   (production build on :3101)
import { chromium, devices } from "@playwright/test";
const BASE = "http://localhost:3101";
const pages = process.argv.slice(2).length ? process.argv.slice(2) : ["/", "/inventory", "/forecast"];
const browser = await chromium.launch();
for (const p of pages) {
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
  await page.request.post(`${BASE}/api/v1/auth/dev-login`, { headers: { "X-Requested-With": "supplylens" }, data: { email: "planner@dev.supplylens.local" } });
  await page.addInitScript(() => { window.__l = []; new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__l.push({ t: Math.round(e.startTime), tag: e.element?.tagName, txt: (e.element?.textContent || e.url || "").slice(0, 60), size: e.size }); }).observe({ type: "largest-contentful-paint", buffered: true }); });
  await page.goto(`${BASE}${p}?ws=uci-research`); await page.waitForLoadState("networkidle"); await page.waitForTimeout(1500);
  const res = await page.evaluate(() => ({ lcp: window.__l, nav: performance.getEntriesByType("navigation")[0]?.responseEnd, fcp: performance.getEntriesByName("first-contentful-paint")[0]?.startTime,
    js: performance.getEntriesByType("resource").filter((r) => r.name.endsWith(".js")).reduce((a, r) => a + (r.transferSize || 0), 0),
    api: performance.getEntriesByType("resource").filter((r) => r.name.includes("/api/")).map((r) => [r.name.split("/api/v1/")[1]?.slice(0, 30), Math.round(r.startTime), Math.round(r.responseEnd)]) }));
  console.log(p, JSON.stringify(res));
  await ctx.close();
}
await browser.close();
