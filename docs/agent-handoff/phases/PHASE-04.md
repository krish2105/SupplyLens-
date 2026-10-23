# Phase 4 — frontend, UX and complete end-to-end workflows

**Dates:** 2026-10-23 (UTC) · **Start:** `main` @ `55e0b1c` · **Brief:** the owner's "Phase 4: frontend, UX and complete E2E
workflows" (PD-017). Evidence `P4-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues → [`../ISSUES.md`](../ISSUES.md);
decisions D-073 … D-077 → root [`DECISIONS.md`](../../DECISIONS.md), PD-017 … PD-020 → [`../DECISIONS.md`](../DECISIONS.md).

**What was and was not tested.** Browsers: Chromium (desktop 1440×900 and Pixel 7 emulation), WebKit (desktop and iPhone 13
emulation) locally; Firefox only in CI (it does not start on this macOS 27 machine, PD-020). No physical device, no manual
screen-reader pass (EXT-05), no Keycloak sign-in. Data: a disposable CI-equivalent stack (`supplylens_p4ci`).

## 1. Journeys (status, tests)
| # | Journey | Status | Covered by |
|---|---|---|---|
| 1 | Sign-in, sign-out, session ending mid-use, role-based offers | **PASS** | workflows J1 ×3, journey (viewer cannot approve), remediation UX-009 (expired session, denied) |
| 2 | Workspace setup, invitations (membership), administration | **PASS** | workflows J2 ×5 (unknown workspace, no workspace, role change audited and restored, failed request + retry, double-clicked export), remediation S18 (CSV onboarding) |
| 3 | Inventory and supplier-data import | **PASS** | remediation S18 (upload, map, quarantine), J11 setup (sales, stock, terms imported and published through the product) |
| 4 | Document ingestion and contract history | **PASS (new feature)** | workflows J4 ×2 (add policy + amendment → history, comparison, in-force citation; clause labels); `tests/test_phase4_web_api.py` |
| 5 | Forecast generation and interpretation | **PASS**; replay-refusal test **SKIPPED** (needs the licensed study's trained champion) | consistency ×2, journey "forecast lab refuses a replay" (skip) |
| 6 | Shortage and inventory-risk analysis | **PASS** | workflows J6 (ranked shortages, keyboard tabs, open in inventory); API test per-location shortage |
| 7 | Scenario planning and constrained replenishment | **PASS** | workflows J7 (baseline vs draft, plan lines), remediation F03 |
| 8 | Supplier evidence and recommendations | **PASS** | workflows J8 (citation opened highlighted), journey (amendment changes the decision), consistency (drawer = evidence version) |
| 9 | Approval, rejection, stale approval, permission | **PASS** | journey (approve), workflows J9 ×3 (reject with reason, stale approval refused with 409, double-click approves once), J1 (viewer refused 403) |
| 10 | Purchase order through the authorised test adapter | **PASS** | journey (sandbox order reconciled, read back line by line), resilience (no duplicate on lost response) |
| 11 | Order status, receipts, reconciliation, replanning | **PASS** | workflows J11 (own workspace: reconciled → replanning orders nothing → partial receipt → open units → still nothing) |
| 12 | Reporting, filtering, export, audit, error recovery | **PASS** | workflows J12 ×3 (filters/search/sort, render error contained, not-found), journey (audit CSV), resilience (offline, WebGL loss, 503) |

Run counts: desktop 99, mobile 45, WebKit 27, iPhone WebKit 7, Firefox 27. CI run 39897951198: 200 passed / 5 skipped
across all five projects (P4-E15); the first push failed 6/8 (digest flaw, one Firefox locator) and was fixed (P4-E12). Locally, three consecutive full runs:
168 passed / 4 skipped each; final run after all changes 174 passed / 4 skipped / 0 failed (P4-E08, P4-E11).

## 2. Defects found and fixed
| ID | Defect (reproduced first) | Fix |
|---|---|---|
| P1-FE-01 | A link or default naming a workspace the user is not in made every request fail | Shell moves to a membership; "No workspace yet" screen |
| P1-FE-02 | Inventory kept one location per SKU (`DISTINCT ON (sku_id)`): other sites' stock vanished | One row per SKU@location with that site's sales (single-site SKUs unchanged); keys, stock-by-location table |
| P2-FE-03 | No lint, no unit tests, e2e untyped | ESLint (0 warnings), Vitest (19), e2e typechecked; all in CI |
| P2-FE-04 | A render error blanked the app | Route/root/global boundaries, not-found page, shell-widget boundaries |
| P2-FE-05 | Mutations minted a key per click | Per-intent keys by default (export, member change, promotion, deletion, onboarding, upload) |
| P2-FE-06 | 24 queries: errors shown as spinners or as "no data" | `QueryError` with retry everywhere; receipts card no longer disappears |
| P2-FE-07 | Stale mapping on another batch; unhandled rejections; drafts following the user | Keyed batch panel; errors shown; draft hook fixed (test fails on old code) |
| P2-FE-08 | Vitals observers re-registered per route | Registered once |
| P2-QA-01 | Reference-case race between parallel tests | Cross-worker lock (`e2e/fixtures.ts`); stock-changing journeys get their own workspace |
| P2-QA-02 | Single-sample lab vitals flaky on CI | Median of three loads, same targets |
| P3-FE-09 (part) | Run enabled while role loading; dev copy; no return path; unguarded stream parse; tabs without panels | All fixed; WAI-ARIA tabs with arrow keys. Open: first-load JS size |
| P3-FE-10 | Demo lockdown explained only after a refused click | Notice and disabled controls up front |
| FE-P4-01 | Clause labels fetched, never shown | Label viewer with occurrences |
| FE-P4-04 | No command palette on phones | Icon trigger below tablet width |
| FE-P4-05 | A session ended elsewhere stranded the screen | Any 401 → sign-in → back to the same screen |
| FE-P4-06 | No way to add a document from the product | Upload (plain text, admins, server known-at, amendments) |
| FE-P4-07 | Mobile CLS regression introduced in this phase (0.14-0.17) | Reserved label space: 0.04-0.07 |

## 3. Files changed (why)
Shell and states: `app/(app)/layout.tsx`, `app/providers.tsx`, `app/login/page.tsx`, `lib/nav.ts`, `components/ui.tsx`,
`components/crash.tsx`, `components/safe-boundary.tsx`, `app/error.tsx`, `app/(app)/error.tsx`, `app/global-error.tsx`,
`app/not-found.tsx`. Data and mutations: `lib/api.ts`, `lib/queries.ts`, `lib/draft.ts`, `components/vitals-reporter.tsx`,
`components/command-palette.tsx`. Screens: admin, approvals, data, exceptions, forecast, inventory, overview, policies,
research, runs, scenarios, settings, market, value; `components/onboarding.tsx`, `floorplan.tsx`, `warehouse3d.tsx`, `chart*.tsx`.
API: `api/routes_core.py` (inventory per location), `api/routes_ops.py` (shortage names the site), `api/routes_decisions.py`
(`POST /documents`), `knowledge/upload.py`, `api/schemas.py`, contracts. Tooling: `eslint.config.mjs`, `vitest.config.mts`,
`tsconfig.e2e.json`, `playwright.config.ts` (Firefox, WebKit, iPhone), `package.json` scripts, CI workflow; tests listed in ISSUES.

## 4. Accessibility and performance
axe (WCAG 2.0 A/AA, 2.1 AA, 2.2 AA): no serious or critical violations on 11 screens (desktop and mobile), admin, settings,
the new upload form and the not-found page; dark-theme contrast on four screens. Keyboard: skip link, focus visibility,
palette focus trap, approval without a mouse, tabs with arrow keys. Lab vitals (median of 3): all pages within LCP 2.5 s /
INP 200 ms / CLS 0.1 on desktop and within the mobile stress budget. **Not done:** manual screen-reader pass, real devices.

## 5. Remaining risks
- FE-P4-08: focus occasionally lost right after load under heavy parallel load (unverified cause).
- Firefox evidence is CI-only; mobile evidence is emulation.
- First-load JavaScript and client-only pages (P3-FE-09 rest); overview mobile LCP was not re-measured on the throttled field profile.
- Document upload accepts plain text only; PDF needs a vetted parser.
- Local `supplylens_p0e2e` keeps polluted reference data (left in place by the no-drop rule).

## 6. Next actions
Phase 5 (data protection and retrieval quality, PERF-P3-09); investigate FE-P4-08 with a CI trace. **Proposal declined for now by the
owner (PD-021):** `e2e` stays optional in branch protection.
