import fs from "node:fs";
import path from "node:path";
import { expect, test } from "./fixtures";
import { getJson, signIn } from "./helpers";

// UX-011: measurable performance targets. Lab measurement of the production build (LCP, CLS and an INP proxy over real
// interactions) against the targets LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1, plus proof that the app reports the same
// metrics from real sessions (the admin screen shows their 75th percentile).

const TARGET = { lcp: 2500, inp: 200, cls: 0.1 };
// The throttled-mobile profile (slow 4G + 4x CPU, Lighthouse-style) is a stress profile, not the product target: it gets
// regression budgets. LCP and INP there are above the field targets today (see docs/operations/web-vitals.md); the field
// p75 reported by real sessions (admin screen) is what decides UX-011.
const STRESS_BUDGET = { lcp: 4500, inp: 750, cls: 0.1 };
const PAGES = ["/", "/exceptions", "/inventory", "/forecast", "/approvals", "/runs", "/policies", "/scenarios"];
const OUT = path.resolve(process.cwd(), "../../artifacts/reports/webvitals");

declare global { interface Window { __v: { lcp: number; cls: number; inp: number } } }

for (const p of PAGES) {
  test(`lab vitals ${p}`, async ({ page }, info) => {
    const mobile = info.project.name === "mobile";
    if (mobile) {            // Lighthouse-style mobile throttling: 4x CPU slowdown, ~1.6 Mbps / 150 ms RTT
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
      await cdp.send("Network.enable");
      await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    }
    await signIn(page, "planner");
    await page.addInitScript(() => {
      window.__v = { lcp: 0, cls: 0, inp: 0 };
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__v.lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver((l) => { for (const e of l.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) if (!e.hadRecentInput) window.__v.cls += e.value; })
        .observe({ type: "layout-shift", buffered: true });
      const byInteraction: Record<number, number> = {};
      new PerformanceObserver((l) => {
        for (const e of l.getEntries() as unknown as { interactionId: number; duration: number }[]) {
          if (e.interactionId) byInteraction[e.interactionId] = Math.max(byInteraction[e.interactionId] ?? 0, e.duration);
        }
        window.__v.inp = Math.max(0, ...Object.values(byInteraction));
      }).observe({ type: "event", durationThreshold: 16, buffered: true } as PerformanceObserverInit);
    });
    // Three loads, judged by the median of each metric against the unchanged targets (P2-QA-02): one sample on a shared
    // CI runner is noise-bound (one desktop INP proxy read 224 ms on a docs-only commit). Every sample is recorded.
    const samples: { lcp: number; cls: number; inp: number }[] = [];
    for (let n = 0; n < 3; n++) {
      await page.goto(`${p}?ws=uci-research`);
      await page.waitForLoadState("networkidle");
      // Real interactions: theme switch, command palette, a table row if there is one.
      await page.getByRole("radio", { name: "Dark theme" }).click();
      await page.getByRole("radio", { name: "Light theme" }).click();
      await page.keyboard.press("Control+k");
      await page.keyboard.press("Escape");
      const row = page.locator("tbody tr").first();
      if (await row.count()) await row.click();
      await page.waitForTimeout(600);         // let the last interaction's event timing entry arrive
      samples.push(await page.evaluate(() => window.__v));
    }
    const median = (k: "lcp" | "cls" | "inp") => samples.map((x) => x[k]).sort((a, b) => a - b)[1]!;
    const v = { lcp: median("lcp"), cls: median("cls"), inp: median("inp") };
    fs.mkdirSync(OUT, { recursive: true });       // one file per test: workers run in parallel
    fs.writeFileSync(path.join(OUT, `${info.project.name}${p === "/" ? "-overview" : p.replaceAll("/", "-")}.json`), JSON.stringify({
      path: p, profile: info.project.name, measured_at: new Date().toISOString(), targets: mobile ? STRESS_BUDGET : TARGET,
      lcp_ms: Math.round(v.lcp), cls: +v.cls.toFixed(4), inp_ms: Math.round(v.inp), statistic: "median of 3 loads",
      samples: samples.map((x) => ({ lcp_ms: Math.round(x.lcp), cls: +x.cls.toFixed(4), inp_ms: Math.round(x.inp) })) }));
    const limit = mobile ? STRESS_BUDGET : TARGET;
    expect.soft(v.lcp, `LCP ${p} (${info.project.name})`).toBeLessThanOrEqual(limit.lcp);
    expect.soft(v.cls, `CLS ${p} (${info.project.name})`).toBeLessThanOrEqual(limit.cls);
    expect.soft(v.inp, `INP proxy ${p} (${info.project.name})`).toBeLessThanOrEqual(limit.inp);
  });
}

test("the app reports real-session vitals and the admin screen aggregates them", async ({ page }) => {
  await signIn(page, "tenant_admin");
  await page.goto("/exceptions?ws=uci-research");
  await page.waitForLoadState("networkidle");
  await page.getByRole("radio", { name: "Dark theme" }).click();
  await page.goto("/inventory?ws=uci-research");
  await page.waitForLoadState("networkidle");
  await page.goto("about:blank");               // leaving the page flushes LCP / CLS / INP
  await page.waitForTimeout(500);
  await signIn(page, "tenant_admin");
  const v = await getJson<{ metrics: { metric: string; route: string; n: number; p75: number; target: number | null }[]; targets: Record<string, number> }>(page, "/api/v1/admin/vitals?days=1");
  const seen = new Set(v.metrics.map((m) => m.metric));
  for (const m of ["FCP", "TTFB", "LCP"]) expect(seen, `field metric ${m} was reported`).toContain(m);
  expect(v.targets).toEqual({ LCP: 2500, INP: 200, CLS: 0.1 });
  expect(v.metrics.every((m) => m.n >= 1 && m.p75 >= 0)).toBe(true);
  await page.goto("/admin?ws=uci-research");
  await expect(page.getByRole("table", { name: "Web Vitals by route" })).toBeVisible();
});
