// Non-happy states and overlays for visual review (Phase 4B): empty, loading, error, offline, permission denied and modal
// states, light and dark, desktop and mobile. States that the data cannot produce on demand are induced by holding or
// replacing one API response in the browser (route interception); the app's own rendering is what is captured.
//
//   node scripts/capture-states.mjs <out-dir> [base-url]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = process.argv[2] ?? "../../artifacts/screens/phase4b/after/states";
const BASE = process.argv[3] ?? "http://localhost:3100";
const json = (body, status = 200) => (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

// name, path, workspace, role, setup(page, ctx) before navigation, after(page) once loaded
const STATES = [
  ["empty-inventory", "/inventory?eff=2001-01-01", "uci-research", "viewer"],
  ["empty-filtered-inventory", "/inventory", "uci-research", "viewer", null, async (p) => p.getByPlaceholder(/Search code or description/).fill("zzz-no-match")],
  ["empty-runs", "/runs", "demo", "planner", async (p) => p.route("**/api/v1/agent-runs", json([]))],
  ["empty-policies", "/policies", "demo", "viewer", async (p) => p.route("**/api/v1/documents", json([]))],
  ["empty-approvals-stale-tab", "/approvals", "demo", "approver", null, async (p) => p.getByRole("tab", { name: "Stale" }).click()],
  ["loading-overview", "/", "uci-research", "viewer", async (p) => p.route("**/api/v1/overview", () => new Promise(() => {}))],
  ["error-overview", "/", "uci-research", "viewer", async (p) => p.route("**/api/v1/overview", json({ code: "server_error", message: "The server hit an unexpected error.", reference: "3f9c2a7e1b6d4c08" }, 500))],
  ["error-admin-members", "/admin", "uci-research", "tenant_admin", async (p) => p.route("**/api/v1/admin/members*", json({ code: "server_error", message: "The server hit an unexpected error.", reference: "3f9c2a7e1b6d4c08" }, 500))],
  ["offline-inventory", "/inventory", "uci-research", "viewer", null, async (p, ctx) => { await ctx.setOffline(true); await p.getByRole("button", { name: /Units\/day/ }).click().catch(() => {}); await p.getByLabel("Workspace").selectOption("demo").catch(() => {}); }],
  ["denied-admin-viewer", "/admin", "uci-research", "viewer"],
  ["denied-approvals-403", "/approvals", "demo", "viewer", async (p) => p.route("**/api/v1/actions?*", json({ code: "forbidden", message: "not allowed" }, 403))],
  ["busy-503", "/inventory", "uci-research", "viewer", async (p) => p.route("**/api/v1/inventory*", json({ code: "overloaded", message: "The service is at capacity; retry in a few seconds." }, 503))],
  ["modal-command-palette", "/", "uci-research", "viewer", null, async (p) => { await p.getByRole("button", { name: "Open command palette" }).click(); await p.getByRole("combobox").fill("inv"); }],
  ["modal-compare-versions", "/policies", "demo", "viewer", null, async (p) => p.getByRole("button", { name: "Compare versions" }).first().click()],
  ["no-workspace", "/", null, "viewer", async (p) => p.route("**/api/v1/me", async (route) => { const r = await route.fetch(); route.fulfill({ response: r, json: { ...(await r.json()), memberships: [] } }); })],
  ["demo-lockdown-admin", "/admin", "uci-research", "tenant_admin", async (p) => p.route("**/api/v1/auth/config", json({ environment: "demo", dev_login: true, oidc: false, oidc_login_url: null, disposable: false }))],
];

const VIEWS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };

const browser = await chromium.launch();
for (const [vname, viewport] of Object.entries(VIEWS)) for (const theme of ["light", "dark"]) {
  const dir = join(OUT, `${theme}-${vname}`);
  mkdirSync(dir, { recursive: true });
  for (const [name, path, ws, role, setup, after] of STATES) {
    const ctx = await browser.newContext({ viewport, isMobile: vname === "mobile", hasTouch: vname === "mobile", colorScheme: theme, reducedMotion: "reduce" });
    await ctx.addInitScript((t) => { try { localStorage.setItem("supplylens-theme", t); } catch { /* none */ } }, theme);
    await ctx.request.post(`${BASE}/api/v1/auth/dev-login`, { headers: { "X-Requested-With": "supplylens" }, data: { email: `${role}@dev.supplylens.local` } });
    const page = await ctx.newPage();
    if (setup) await setup(page, ctx);
    const url = `${BASE}${path}${ws ? `${path.includes("?") ? "&" : "?"}ws=${ws}` : ""}`;
    await page.goto(url, { waitUntil: name.startsWith("loading") ? "domcontentloaded" : "networkidle", timeout: 30_000 }).catch(() => {});
    if (after) await after(page, ctx).catch((e) => console.log(name, "after:", e.message.split("\n")[0]));
    await page.waitForTimeout(name.startsWith("busy") || name.startsWith("error") ? 9000 : 1200);   // retries settle before the shot
    await page.screenshot({ path: join(dir, `${name}.png`) });
    await ctx.close();
  }
}
await browser.close();
console.log(`${Object.keys(VIEWS).length * 2 * STATES.length} state screenshots`);
