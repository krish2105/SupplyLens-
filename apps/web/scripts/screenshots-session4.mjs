// Fresh evidence screenshots for the session-4 changes, labelled with the code revision, viewport, theme and state.
// Usage: SUPPLYLENS_WEB_URL=http://localhost:3101 node scripts/screenshots-session4.mjs
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const BASE = process.env.SUPPLYLENS_WEB_URL ?? "http://localhost:3100";
const OUT = new URL("../../../docs/screenshots/session4/", import.meta.url).pathname;
const REV = execSync("git rev-parse --short HEAD").toString().trim() + (execSync("git status --porcelain").toString().trim() ? "-dirty" : "");
mkdirSync(OUT, { recursive: true });
const DESKTOP = { width: 1440, height: 900 }, MOBILE = { width: 375, height: 812 };

const shots = [
  { name: "login", path: "/login", theme: "light", vp: DESKTOP, role: null, state: "sign-in with welcome art (A01), OIDC + dev accounts" },
  { name: "login", path: "/login", theme: "dark", vp: DESKTOP, role: null, state: "sign-in, dark theme" },
  { name: "login", path: "/login", theme: "light", vp: MOBILE, role: null, state: "sign-in at 375 px (art hidden)" },
  { name: "scenarios-basis", path: "/scenarios?ws=uci-research", theme: "light", vp: DESKTOP, role: "planner", state: "F03: safety buffer not applicable under lead-time demand" },
  { name: "scenarios-basis", path: "/scenarios?ws=uci-research", theme: "dark", vp: DESKTOP, role: "planner", state: "F03 dark theme" },
  { name: "data-onboarding", path: "/data?ws=uci-research", theme: "light", vp: DESKTOP, role: "tenant_admin", state: "S18 onboarding wizard", scroll: 2600 },
  { name: "research-registry", path: "/research?ws=uci-research", theme: "light", vp: DESKTOP, role: "planner", state: "S16 reviewed headlines and superseded runs" },
  { name: "research-registry", path: "/research?ws=uci-research", theme: "dark", vp: DESKTOP, role: "planner", state: "S16 dark theme", scroll: 1400 },
  { name: "settings-connections", path: "/settings?ws=uci-research", theme: "light", vp: DESKTOP, role: "planner", state: "A11 no live ERP connector; OIDC status", scroll: 500 },
  { name: "approvals-empty", path: "/approvals?ws=uci-research", theme: "dark", vp: DESKTOP, role: "approver", state: "A08 no pending items in this view" },
  { name: "inventory-filtered", path: "/inventory?ws=uci-research", theme: "light", vp: DESKTOP, role: "planner", state: "A07 zero matches for a search", search: "zzzz-no-such-sku", scroll: 700 },
  { name: "investigations-empty", path: "/runs?ws=contract-research", theme: "light", vp: DESKTOP, role: "viewer", state: "A15 no runs in this workspace" },
  { name: "admin-members", path: "/admin?ws=uci-research", theme: "light", vp: DESKTOP, role: "tenant_admin", state: "S18 membership administration" },
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const manifest = [];
for (const s of shots) {
  const ctx = await browser.newContext({ viewport: s.vp, deviceScaleFactor: 1, colorScheme: s.theme });
  await ctx.addInitScript((t) => localStorage.setItem("supplylens-theme", t), s.theme);
  const page = await ctx.newPage();
  if (s.role) await page.request.post(`${BASE}/api/v1/auth/dev-login`, { headers: { "X-Requested-With": "supplylens" }, data: { email: `${s.role}@dev.supplylens.local` } });
  await page.goto(BASE + s.path);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2500);
  if (s.search) { await page.getByRole("searchbox").first().fill(s.search).catch(() => page.locator('input[type="search"], input[placeholder*="Search"]').first().fill(s.search)); await page.waitForTimeout(800); }
  if (s.scroll) { await page.mouse.wheel(0, s.scroll); await page.waitForTimeout(700); }
  const file = `${s.name}-${s.theme}-${s.vp.width}w-${REV}.png`;
  await page.screenshot({ path: OUT + file });
  manifest.push({ file, route: s.path, theme: s.theme, viewport: `${s.vp.width}x${s.vp.height}`, role: s.role, state: s.state, revision: REV,
                  captured_at: new Date().toISOString() });
  console.log("captured", file);
  await ctx.close();
}
await browser.close();
writeFileSync(OUT + "manifest.json", JSON.stringify({ base_url: BASE, revision: REV, shots: manifest }, null, 2) + "\n");
