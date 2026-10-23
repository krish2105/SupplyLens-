// Screen capture for visual review (Phase 4B): every route, light and dark, desktop / tablet / mobile, plus non-happy
// states, from the running app. Screenshots are of the real product only. Per page it also records horizontal overflow,
// failed requests (images included), console errors and text clipped by its own box.
//
//   node scripts/capture-screens.mjs <out-dir> [base-url]      (base defaults to http://localhost:3100)
// Raw captures are large: write them under artifacts/ (git-ignored); docs/screenshots/phase4b holds the reviewed set.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const OUT = process.argv[2] ?? "../../artifacts/screens/phase4b/after";
const BASE = process.argv[3] ?? "http://localhost:3100";
const WIDTHS = { desktop: { width: 1440, height: 900 }, tablet: { width: 834, height: 1112 }, mobile: { width: 390, height: 844 } };
const THEMES = ["light", "dark"];
// route, workspace, role, wait-for text (proves the screen rendered its data)
const SCREENS = [
  ["login", "/login", null, null, "Welcome to SupplyLens"],
  ["overview", "/", "uci-research", "planner", "Stock positions"],
  ["overview-demo", "/", "demo", "planner", null],
  ["exceptions", "/exceptions", "uci-research", "planner", "What needs a decision"],
  ["inventory", "/inventory", "uci-research", "planner", "Stock positions by product"],
  ["forecast", "/forecast", "uci-research", "planner", null],
  ["scenarios", "/scenarios", "uci-research", "planner", null],
  ["runs", "/runs?known=2026-10-20T09:00:00.000Z&eff=2026-10-20", "demo", "planner", null],
  ["approvals", "/approvals", "demo", "approver", "Review exact payloads"],
  ["policies", "/policies", "demo", "planner", "Supplier terms, versions and citations"],
  ["market", "/market", "contract-research", "viewer", null],
  ["research", "/research", "uci-research", "viewer", null],
  ["value", "/value", "uci-research", "viewer", null],
  ["data", "/data", "uci-research", "tenant_admin", null],
  ["admin", "/admin", "uci-research", "tenant_admin", "Members, jobs, models and audit"],
  ["settings", "/settings", "uci-research", "viewer", null],
  ["not-found", "/no-such-page", null, "viewer", "There is no page at this address"],
];

async function signIn(ctx, role) {
  if (!role) return;
  const r = await ctx.request.post(`${BASE}/api/v1/auth/dev-login`, { headers: { "X-Requested-With": "supplylens" },
    data: { email: `${role}@dev.supplylens.local` } });
  if (!r.ok()) throw new Error(`sign-in ${role}: ${r.status()}`);
}

async function inspect(page) {
  return page.evaluate(() => {
    const overflowX = document.documentElement.scrollWidth - window.innerWidth;
    const clipped = [];
    for (const el of document.querySelectorAll("body *")) {
      const s = getComputedStyle(el);
      if (!el.childNodes.length || s.display === "none" || s.visibility === "hidden") continue;
      const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!hasText) continue;
      const truncates = s.textOverflow === "ellipsis";
      const hidden = ["hidden", "clip"].includes(s.overflowX) || ["hidden", "clip"].includes(s.overflowY);
      if (hidden && !truncates && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 2)) {
        clipped.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)}: ${el.textContent.trim().slice(0, 50)}`);
      }
    }
    const offscreen = [...document.querySelectorAll("button, a, input, select")].filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > window.innerWidth + 1 || r.left < -1) && getComputedStyle(e).position !== "fixed";
    }).map((e) => (e.getAttribute("aria-label") || e.textContent || e.tagName).trim().slice(0, 40));
    const images = [...document.images].map((i) => ({ src: i.currentSrc.split("/").pop(), ok: i.complete && i.naturalWidth > 0,
      shown: `${Math.round(i.getBoundingClientRect().width)}x${Math.round(i.getBoundingClientRect().height)}`,
      natural: `${i.naturalWidth}x${i.naturalHeight}` }));
    return { overflowX, clipped: clipped.slice(0, 12), offscreen: offscreen.slice(0, 12), images };
  });
}

async function run() {
  const browser = await chromium.launch();
  const report = [];
  for (const [wname, viewport] of Object.entries(WIDTHS)) {
    for (const theme of THEMES) {
      const dir = join(OUT, `${theme}-${wname}`);
      mkdirSync(dir, { recursive: true });
      for (const [name, path, ws, role, waitText] of SCREENS) {
        const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, isMobile: wname === "mobile", hasTouch: wname !== "desktop",
          colorScheme: theme, reducedMotion: "reduce" });
        await ctx.addInitScript((t) => { try { localStorage.setItem("supplylens-theme", t); } catch { /* none */ } }, theme);
        await signIn(ctx, role);
        const page = await ctx.newPage();
        const failed = [], consoleErrors = [];
        page.on("response", (r) => { if (r.status() >= 400 && !r.url().includes("/api/v1/me")) failed.push(`${r.status()} ${new URL(r.url()).pathname}`); });
        page.on("requestfailed", (r) => failed.push(`FAILED ${new URL(r.url()).pathname}`));
        page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 160)); });
        const url = `${BASE}${path}${ws ? `${path.includes("?") ? "&" : "?"}ws=${ws}` : ""}`;
        await page.goto(url, { waitUntil: "networkidle" }).catch(() => {});
        if (waitText) await page.getByText(waitText).first().waitFor({ timeout: 15_000 }).catch(() => {});
        await page.waitForTimeout(800);           // charts and 3D settle (reduced motion)
        await page.screenshot({ path: join(dir, `${name}.png`) });
        await page.screenshot({ path: join(dir, `${name}-full.png`), fullPage: true });
        if (name === "exceptions") {             // what stays on screen once the reader scrolls (sticky header)
          await page.mouse.wheel(0, 900); await page.waitForTimeout(400);
          await page.screenshot({ path: join(dir, `${name}-scrolled.png`) });
        }
        report.push({ screen: name, theme, width: wname, url: path, role, ...(await inspect(page)), failed, consoleErrors });
        await ctx.close();
      }
    }
  }
  writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 1));
  await browser.close();
  const issues = report.filter((r) => r.overflowX > 1 || r.failed.length || r.consoleErrors.length || r.clipped.length || r.offscreen.length
    || r.images.some((i) => !i.ok));
  console.log(`${report.length} screens captured; ${issues.length} with findings`);
}

run().catch((e) => { console.error(e); process.exit(1); });
