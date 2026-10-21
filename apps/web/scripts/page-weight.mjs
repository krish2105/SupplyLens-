// Dev tool: transfer size by resource type for a page's first load (web app running on :3100).
// Usage: node scripts/page-weight.mjs /exceptions /inventory
import { chromium } from "@playwright/test";
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH, args: ["--no-sandbox"] } : {});
for (const path of process.argv.slice(2).length ? process.argv.slice(2) : ["/exceptions"]) {
  const ctx = await browser.newContext({ baseURL: "http://localhost:3100" });
  const page = await ctx.newPage();
  await page.request.post("/api/v1/auth/dev-login", { headers: { "X-Requested-With": "supplylens" }, data: { email: "planner@dev.supplylens.local" } });
  const by = {}; const files = [];
  page.on("response", async (r) => {
    const t = r.request().resourceType(); const len = Number((await r.allHeaders())["content-length"] ?? 0) || (await r.body().catch(() => Buffer.alloc(0))).length;
    by[t] = (by[t] ?? 0) + len; if (t === "script") files.push([len, r.url().split("/").pop()]);
  });
  await page.goto(path + "?ws=uci-research"); await page.waitForLoadState("networkidle");
  console.log(path, Object.fromEntries(Object.entries(by).map(([k, v]) => [k, Math.round(v / 1024) + " KB"])));
  console.log("  largest scripts:", files.sort((a, b) => b[0] - a[0]).slice(0, 4).map(([l, n]) => `${n} ${Math.round(l / 1024)}KB`).join(", "));
  await ctx.close();
}
await browser.close();
