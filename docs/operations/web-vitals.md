# Web Vitals (UX-011)

Targets (field, 75th percentile): **LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1**.

## What is measured, and what that does and does not prove

| Source | What it is | Where |
|---|---|---|
| Laboratory run | Production build driven by Playwright; LCP, CLS and an INP proxy (slowest of the theme switch, palette open/close and a table-row click) per page | `apps/web/e2e/vitals.spec.ts`, aggregated by `scripts/summarise_vitals.py` into `artifacts/reports/webvitals-lab.json` |
| Field | Every signed-in session reports LCP/INP/CLS/FCP/TTFB to `POST /api/v1/telemetry/vitals` (rate-limited, validated, tenant-scoped); the Administration screen shows the 75th percentile | `apps/web/components/vitals-reporter.tsx`, `GET /api/v1/admin/vitals` |

The lab numbers below are **laboratory measurements on one machine, one run per page**. They are not field data and not a
statement about any user's device. UX-011 is decided by the field p75 once real sessions exist; there are none yet.

Conditions — desktop: Chromium headless 1440×900, no throttling, loopback network. Mobile: phone viewport, 4× CPU slowdown,
150 ms RTT, 1.6 Mbps down (Lighthouse-style slow 4G). Data: the synthetic browser-test workspace (36 products).

## Results (2026-10-21)

| profile | page | LCP (ms) | INP proxy (ms) | CLS |
|---|---|---:|---:|---:|
| desktop | / | 1388 | 128 | 0.0884 |
| desktop | /approvals | 276 | 80 | 0.0041 |
| desktop | /exceptions | 220 | 72 | 0.0063 |
| desktop | /forecast | 328 | 152 | 0.0494 |
| desktop | /inventory | 228 | 112 | 0.0012 |
| desktop | /policies | 268 | 72 | 0.0001 |
| desktop | /runs | 320 | 64 | 0.0012 |
| desktop | /scenarios | 288 | 96 | 0.0001 |
| mobile (throttled) | / | 3816 | 120 | 0.0053 |
| mobile (throttled) | /approvals | 2860 | 120 | 0.0161 |
| mobile (throttled) | /exceptions | 3008 | 144 | 0.0098 |
| mobile (throttled) | /forecast | 2980 | 136 | 0.0006 |
| mobile (throttled) | /inventory | 3156 | **208** | 0.0057 |
| mobile (throttled) | /policies | 2836 | 96 | 0.0006 |
| mobile (throttled) | /runs | 3044 | 120 | 0 |
| mobile (throttled) | /scenarios | 2812 | 120 | 0.001 |

**Desktop meets all three targets on every page.** **Throttled mobile does not meet LCP (2.8–3.8 s against 2.5 s) and one
page exceeds INP (inventory, 208 ms against 200 ms).** CLS is within target everywhere. The mobile profile is a stress
profile (it is deliberately harsher than a mid-range phone on 4G); the test enforces regression budgets there
(LCP 4.5 s, INP 750 ms) and the targets on desktop. It is reported here as a known gap, not hidden by the budget.

## What was changed because of these measurements

* Charts (ECharts) and the 3D warehouse are separate lazy chunks; first paint no longer downloads them. Shared JavaScript
  per page fell by about 61 %.
* Space is reserved for the decision-clock strip, charts, inputs and the stacked mobile layout, and queries that gate
  nothing visible no longer block rendering: each source of layout shift found during measurement was removed one by one; CLS is now at most 0.088 on every page.
* `isLoading` (first load) is distinguished from `isFetching` (background refresh), so a refetch no longer replaces content
  with skeletons.

## What would move mobile LCP below 2.5 s (not done)

LCP on mobile is dominated by download + parse of the Next.js client bundle on a 4× slower CPU, then the first data fetch.
Server-rendering the first screen with data (instead of a client-side fetch after hydration) is the change with the
largest effect; it needs the server to hold the session cookie and call the API directly, which is a larger change to the
data layer than this work item. Until then the mobile LCP gap stands.

## Re-running

```
cd apps/web && NEXT_DIST_DIR=.next-build npx next build && NEXT_DIST_DIR=.next-build npx next start --port 3100 &
npx playwright test --project vitals-desktop --project vitals-mobile --workers 1   # needs the API and worker running
uv run python scripts/summarise_vitals.py      # rewrites artifacts/reports/webvitals-lab.json
```

Run the lab measurements alone, one test at a time, with nothing else loading the machine. Run beside other browser
suites they measure the machine's load, not the app: on CI the desktop INP proxy read 224–232 ms on `/` and `/inventory`
while Firefox and WebKit journeys ran in parallel, and locally, with every core busy, the same interactions took
0.7–1.7 s with or without WebGL (QA-4B-01). CI runs them in their own step after the other suites; the targets did not
change.
