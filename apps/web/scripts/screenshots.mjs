// Capture README screenshots from a running local stack (web :3100, API :8000).
// Usage: node scripts/screenshots.mjs
import { chromium } from "@playwright/test";

const BASE = process.env.SUPPLYLENS_WEB_URL ?? "http://localhost:3100";
const OUT = new URL("../../../docs/images/", import.meta.url).pathname;
const shots = [
  { name: "overview-dark", path: "/?ws=uci-research&sku=85123A", theme: "dark", role: "planner", wait: 4000 },
  { name: "overview-light", path: "/?ws=uci-research&sku=85123A", theme: "light", role: "planner", wait: 4000 },
  { name: "forecast-lab", path: "/forecast?ws=uci-research&sku=85123A", theme: "dark", role: "planner", wait: 3000, scroll: 900 },
  { name: "research", path: "/research?ws=uci-research", theme: "light", role: "planner", wait: 3000 },
  { name: "exceptions", path: "/exceptions?ws=uci-research", theme: "dark", role: "planner", wait: 2500 },
  { name: "policies", path: "/policies?ws=uci-research&sku=85123A", theme: "light", role: "planner", wait: 2500 },
  { name: "market", path: "/market?ws=contract-research", theme: "dark", role: "viewer", wait: 3000 },
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
for (const s of shots) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: s.theme });
  await ctx.addInitScript((t) => localStorage.setItem("supplylens-theme", t), s.theme);
  const page = await ctx.newPage();
  await page.request.post(`${BASE}/api/v1/auth/dev-login`, { headers: { "X-Requested-With": "supplylens" }, data: { email: `${s.role}@dev.supplylens.local` } });
  await page.goto(BASE + s.path);
  await page.waitForLoadState("networkidle");
  if (s.name === "policies") {
    await page.getByRole("button", { name: "Search evidence" }).click();
    await page.waitForTimeout(1500);
  }
  await page.waitForTimeout(s.wait);
  if (s.scroll) await page.mouse.wheel(0, s.scroll);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}${s.name}.png` });
  console.log("captured", s.name);
  await ctx.close();
}
await browser.close();
