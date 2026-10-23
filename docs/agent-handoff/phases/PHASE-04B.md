# Phase 4B — visual UI, UX and asset quality gate

**Date:** 2026-10-23 (UTC) · **Start:** `main` @ `98c838a` · **Brief:** the owner's "Phase 4B: complete visual UI, UX and asset
quality gate". Evidence `P4B-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues `UI-4B-..` → [`../ISSUES.md`](../ISSUES.md);
decisions D-078 … D-080 → root [`DECISIONS.md`](../../DECISIONS.md). The existing design language was kept: no screen was
redesigned, no colour, type or spacing token changed.

**What was and was not tested.** Every screenshot is of the running product on the disposable CI-equivalent stack
(`supplylens_p4ci`, synthetic e2e fixture in UCI Research, fictional Demo workspace); none is generated or mocked except
where a state was induced by holding or replacing one API response (listed in §1). Browsers: Chromium (desktop, tablet and
Pixel 7 / 390 px emulation), WebKit (desktop, iPhone 13 emulation). Firefox runs in CI only (PD-020). No physical device,
no manual screen-reader pass (EXT-05).

## 1. How the screens were reviewed
- `apps/web/scripts/capture-screens.mjs`: 17 screens × light/dark × desktop 1440×900, tablet 834×1112, phone 390×844
  (102 captures, viewport + full page), each with a probe: horizontal overflow, controls outside the viewport, text clipped
  by its own box, image natural vs displayed size, failed requests, console errors (`report.json`).
- `apps/web/scripts/capture-states.mjs`: 16 states × light/dark × desktop/phone (64): empty (date with no snapshot,
  filtered to nothing, no runs*, no documents*, empty queue), loading (overview held*), error (overview 500*, members 500*),
  offline (browser offline), permission denied (viewer on Administration; approvals 403*), busy (inventory 503*), modals
  (command palette, version comparison), no workspace (memberships emptied*), demo lockdown (auth config "demo"*).
  \* = induced by replacing or holding that one API response in the browser.
- Raw captures (≈96 MB) are in `artifacts/screens/phase4b/{before,after}` (git-ignored; re-run the scripts to regenerate).
  Committed, reviewed set: `docs/screenshots/phase4b/` — `sheets/` (contact sheet per theme × width, before and after,
  screens and states), `defects/` (before/after pair per defect), `before-report.json`, `after-report.json`.

## 2. Findings and fixes, screen by screen
Every defect was seen in a screenshot first, fixed, re-captured, and pinned by a test that **fails on the previous code**
(P4B-E03, P4B-E04) unless noted.

| ID | Screen / width | Defect (before) | Fix | Before → after |
|---|---|---|---|---|
| UI-4B-01 | Sign-in, phone and tablet | Card wider than the screen: account buttons and e-mail addresses cut off at the right edge | Card `w-full`, single column below md, padding scales, account button stacks name / role / e-mail with `break-all` (`app/login/page.tsx`) | `defects/D1-login-phone-{before,after}.webp` |
| UI-4B-02 | Every screen, phone | Sticky header + decision clock held 307 of 844 px; content scrolled underneath it | Header sticky from md (768 px) up only (`app/(app)/layout.tsx`); `scroll-padding-top` only where the header is sticky (`app/globals.css`) | `defects/D2-header-after-scroll-phone-*` |
| UI-4B-03 | Every screen, phone and tablet (< lg) | Section links as a horizontally clipped strip: 10 of 15 sections off-screen, no current-section indicator | "Sections" menu: trigger shows the current section; left sheet (Radix Dialog) with grouped links, `aria-current`, 44 px targets, Escape/close returns focus; still a `navigation` landmark named "Sections" | `defects/D3-section-navigation-phone{,-dark}-*`; visual baseline `sections-menu-phone-*` |
| UI-4B-04 | Value, Research, Forecast, Data admission; phone | 7 tables wider than a phone, clipped by their cards; value-ledger figures touching | `TableScroll` (`components/ui.tsx`): a focusable, labelled region ("… , scrollable") that scrolls inside the card; ledger numeric cells right-aligned, `whitespace-nowrap`, column gaps | `defects/D4-value-ledger-phone-*` |
| UI-4B-05 | Supplier market (Contract research); clock rail | Contract research was told "Switch to Contract research"; the clock rail showed empty dates with no reason | Message per workspace (`api/routes_market.py`): Contract research says no awards were imported and how they are loaded; other workspaces are pointed to it. Clock rail says the workspace has no operational date, only when a loaded overview says so (a failed one says nothing) (`components/clock-rail.tsx`) | `defects/D5-market-contract-research-*` |
| UI-4B-06 | Investigations, phone | Mode select wider than the screen | Full width below sm (`app/(app)/runs/page.tsx`) | `defects/D6-runs-mode-phone-*` |
| UI-4B-07 | Exceptions | **Misleading synthetic result:** a SKU with no recorded selling price showed revenue at risk / tied-up value of £0.00 next to a high-severity shortage | `materiality_minor` is null with the reason ("no selling price recorded in the last 90 days, so revenue at risk is not estimated"); the screen shows the reason (`api/routes_ops.py`, `exceptions/page.tsx`); ranking unchanged | `defects/D7-exceptions-without-price-*` |
| UI-4B-08 | Overview, loading | While the overview loaded, UCI Research was labelled "Fictional demo workspace" and "No sales dataset in this workspace" | Workspace label, provenance sentence and the admitted-data card wait for the overview (skeletons) (`app/(app)/page.tsx`) | `defects/D8-overview-loading-*` |
| UI-4B-09 | Inventory (error, busy, offline, empty); overview on phones | An empty 3D warehouse was drawn under the error/empty message; the label read "Snapshot — ·"; on phones an empty workspace got an empty floor plan instead of the empty state | Layout panel says why there is nothing to lay out; label "No snapshot to show"; overview checks for no records before choosing 2D/3D (`inventory/page.tsx`, `app/(app)/page.tsx`) | `defects/D9-inventory-busy-*`, `defects/D9-inventory-empty-phone-*` |
| UI-4B-10 | Policies & evidence, < xl | "Compare versions" / opening a version or a citation updated a panel far below the list: nothing visible happened | The reader reserves a screen's height while open on stacked layouts, takes focus and scrolls to the top; focus is moved before the smooth scroll (focusing during it cancelled the scroll — found in testing) (`policies/page.tsx`) | `defects/D10-compare-versions-phone-*` |
| UI-4B-11 | Tablet, every screen | Sticky header is 176 px at 834 px but anchors and focused elements reserved 144 px (audit S17 value): they landed under the header | The shell measures the header (`--header-h`, ResizeObserver) and `scroll-padding-top` uses it (`layout.tsx`, `globals.css`) | probe P4B-E10 (reader top 200 px, header bottom 176 px) |
| UI-4B-12 | Every chart | ECharts animated in for ~1 s even with reduced motion requested | `animation: false` under `prefers-reduced-motion: reduce` (`components/chart-impl.tsx`) | — (behaviour; visual baselines run with reduced motion) |
| UI-4B-13 | Exceptions | Two requests on first load: one without a date, cancelled, then the same date once the overview arrived (the "FAILED /api/v1/exceptions" in the before probe) | Without a replayed date the API default is used, as on Inventory (`exceptions/page.tsx`) | `before-report.json` vs `after-report.json` |

Screens reviewed with **no defect found** (both themes, three widths): Administration, Data admission, Settings, Approvals,
Scenario studio, Forecast lab, Research, not-found, the no-workspace screen, demo-lockdown notice, permission-denied and
offline states, the command palette. Dark mode contrast, chart colours following the theme (ECharts theme sync), WebGL →
2D fallback and the planning context (workspace, dates, selected SKU in the URL) behaved as in Phase 4 and stay covered by
its tests.

**Probe totals (102 captures each).** Horizontal page overflow: 0 → 0. Captures with interactive controls outside the
viewport (skip link excluded): **62 → 2** (the 2 are inventory table headers inside the scrollable table region, by
design). Broken images: 0 → 0. Aborted requests: 1 → 0.

## 3. Code changes
Web: `app/(app)/layout.tsx` (sections menu, sticky from md, measured header), `app/globals.css`, `app/login/page.tsx`,
`app/(app)/page.tsx`, `inventory/page.tsx`, `exceptions/page.tsx`, `policies/page.tsx`, `runs/page.tsx`, `value/page.tsx`,
`research/page.tsx`, `forecast/page.tsx`, `components/ui.tsx` (`TableScroll`), `components/onboarding.tsx`,
`components/clock-rail.tsx`, `components/chart-impl.tsx`. API: `api/routes_market.py`, `api/routes_ops.py` (no schema or
contract change; `materiality_minor` was already nullable). Tooling: `scripts/capture-screens.mjs`,
`scripts/capture-states.mjs`, `playwright.config.ts` (`visual` project; desktop ignores it; phone runs the new spec), CI
(`.github/workflows/ci.yml`: screenshot regression step before the suites), `deploy/vercel-api/source.sha256` re-pinned.
Tests: `e2e/ui-quality.spec.ts` (10 tests × desktop/phone), `e2e/visual.spec.ts` (42 screenshots),
`tests/test_phase4b.py` (2).

## 4. Illustrations (A01–A16)
Reviewed against `docs/design/illustrations.md`, `components/illustration.tsx`, `lib/illustrations.json` and the source
PNGs. **Reused unchanged (13):** A01, A03–A12, A14, A15 — each matches its state (asserted in tests: filtered-to-nothing →
`no-results`, empty queue → `no-pending-work`, 403 → `restricted-access`, offline → `connection-paused`; welcome art never
on a populated screen). Derivatives are 360 px (A01 1120 px) for 96–144 px display (A01 342–450 px): sharp at 2×; every
image request succeeded in all 102 probed captures. Art is never used for data, status or charts. **Rejected (kept withheld, D-040
reconfirmed):** A02, A13, A16 — on review each also implies facts the state does not have: A02's tray already holds lined
paper and the sheets carry text, a table and a pie chart (data present); A13's warehouse holds cartons and its four sites
are joined (stock and a network exist), and the source is visibly soft from upscaling; A16 balances two cartons (a value
judgement on an empty study). **Replacement necessary?** No: those states read clearly with text and an icon. Briefs for
optional replacements are in §8; **no image was generated or integrated**, source assets and provenance are untouched.

## 5. Accessibility and responsive results
axe (WCAG 2.0 A/AA, 2.1 AA, 2.2 AA) on 17 screens, desktop and phone: no serious or critical violations (layout and a11y
specs, part of the matrix); dark-theme contrast clean on four screens. New: sections menu is a labelled dialog with the
current page marked and focus returned on close; scrollable tables are focusable named regions; the policy reader takes
focus when it opens off-screen; charts respect reduced motion. Responsive: no page-level horizontal scroll on any of the
102 captures; every control within the viewport at 390 px except table headers inside their own scroll region.

## 6. Browser and end-to-end results
| Run | Result |
|---|---|
| Behaviour spec on the **pre-fix build** (`HEAD` built in a scratch worktree, same API) | 12 failed / 5 passed / 3 skipped — every phone defect and the overview, clock-rail, inventory and table checks fail; the market message passes there because it is server-side (pinned by pytest instead); the illustration check is a guard |
| Behaviour spec on the fixed build | 17 passed / 3 skipped (phone-only checks at desktop width) |
| Full local matrix (desktop, Pixel 7, WebKit, iPhone 13), twice | **191 passed, 7 skipped, 0 failed** each time (Phase 4 ended at 174/4) |
| Screenshot regression (`--project visual`) | 42 baselines (darwin), reviewed by eye on contact sheets, then 3 passing comparison runs (two consecutive, one after the full matrix had changed data) |
| Approval and ERP journeys (journey, workflows, resilience specs) | unchanged and passing in the matrix |
| Lab Web Vitals (median of 3, desktop and phone) | all within LCP 2.5 s / INP 200 ms / CLS 0.1 (vitals spec in the matrix) |
| Backend | ruff clean; pytest **421 passed, 6 skipped**; contracts match; hosted digest re-pinned |
| Web | ESLint 0 warnings; Vitest 19; typecheck (app + e2e); `npm audit` 0 high |

**Screenshot regression in CI.** Baselines are per platform. Until Linux baselines are committed, CI records them
(artifact `visual-baselines-linux`) with a warning and compares nothing; they must be reviewed by eye before being
committed — never accepted to make a run pass. CI results for this phase: see EVIDENCE P4B-E11.

## 7. Remaining defects and limits
- UI-4B-R1 (low): Contract research shows empty date inputs on the clock rail (now explained by the rail's message).
- UI-4B-R2 (low): offline before the first load shows the inventory skeleton and an empty table header ("0 of 0").
- Linux visual baselines need one review-and-commit cycle before CI enforces them (P4B-E11).
- FE-P4-08 (focus occasionally lost after load under heavy parallel load) unchanged; Firefox local, physical devices and a
  manual screen-reader pass were not run.

## 8. Image briefs awaiting owner approval (not generated)
Common style for all three, matching the published set: soft 3D clay render, isometric three-quarter view from above,
palette from the app tokens and the published pieces: deep teal near `--accent` `#0f6b55`, mint near the dark-theme accent `#63c9a8`, pale mint `--accent-soft` `#dcefe8`, off-white `--bg` `#f4f8f6`, light grey metal; no kraft brown; no text, numbers,
logos, people, charts, tables or currency symbols; transparent background; 1024×1024 PNG, subject centred within the middle
70 %; must read at 96 px. Deliver to `design/source-assets/supplylens/` with an updated `source_manifest.json`, then run
`scripts/optimize_illustrations.py`.
- **A02 import data (Data admission, no batches yet):** an empty deep-teal intake tray with a clean empty interior; two or
  three *blank* off-white sheets hovering above it, edges only (no lines, grid or chart); a mint upward arrow beside the
  tray. Must say "nothing imported yet, upload here", not "data present".
- **A13 empty suppliers (Supplier market, no suppliers):** three small separate building blocks on a pale ground with short
  mint connector stubs that do **not** meet; no cartons in any doorway, no lines between buildings. Must say "no supplier
  network recorded", not an existing network or stock.
- **A16 value study (Value, nothing measured):** an empty off-white ledger board or an empty neutral scale with both pans
  empty and level; no cartons, coins or arrows. Must say "nothing measured yet", not a comparison or a judgement of value.
