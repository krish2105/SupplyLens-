// Dev tool: lists the elements that move during page load (layout-shift sources) for the main screens.
// Usage (web app running on :3100; MOBILE=1 emulates a Pixel 7, THROTTLE=1 slows CPU and network): PLAYWRIGHT_CHROMIUM_PATH=... node scripts/layout-shift.mjs
import { chromium, devices } from "@playwright/test";
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH, args: ["--no-sandbox"] } : {});
for (const path of ["/", "/forecast", "/runs", "/exceptions", "/inventory"]) {
  const ctx = await browser.newContext({ ...(process.env.MOBILE ? devices["Pixel 7"] : { viewport: { width: 1440, height: 900 } }), baseURL: "http://localhost:3100" });
  const page = await ctx.newPage();
  if (process.env.THROTTLE) {   // Lighthouse-style mobile: 4x CPU, ~1.6 Mbps, 150 ms RTT
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
  }
  await page.request.post("/api/v1/auth/dev-login", { headers: { "X-Requested-With": "supplylens" }, data: { email: "planner@dev.supplylens.local" } });
  await page.addInitScript(() => {
    window.__shifts = [];
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4),
      src: e.sources.map((s) => { const n = s.node; return (n?.nodeName ?? "?") + (n?.className && typeof n.className === "string" ? "." + n.className.split(" ").slice(0, 3).join(".") : "") + " " + JSON.stringify([s.previousRect.y|0, s.previousRect.height|0, s.currentRect.y|0, s.currentRect.height|0]); }) }); }).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto(path + "?ws=uci-research");
  await page.waitForLoadState("networkidle"); await page.waitForTimeout(800);
  const s = await page.evaluate(() => window.__shifts);
  console.log("\n=== " + path + "  total " + s.reduce((a, b) => a + b.v, 0).toFixed(3));
  for (const x of s) console.log(x.t + "ms", x.v, x.src.slice(0, 3).join(" | "));
  await ctx.close();
}
await browser.close();
