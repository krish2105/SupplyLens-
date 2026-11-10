# Phase 8 — Course coverage, responsible AI and the presentation pack

**Owner brief:** `docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md` (sessions 8A, 8B, 8C) and
`PHASE-08_PLANNING_CONTEXT.md`. The owner's session prompt named a "v5" brief; no such file existed in the pack or on the
machine, and the owner chose v4 plus the prompt's added rule: never do the owner's individual work (no lab reports,
exercise or quiz answers) (D-100). Evidence `P8-E..` → [`../EVIDENCE.md`](../EVIDENCE.md); issues →
[`../ISSUES.md`](../ISSUES.md); decisions D-100 … → root [`DECISIONS.md`](../../../DECISIONS.md).

## Session 8A — before Week 6 (2026-11-10)

**Start:** `main` @ `9f8da12` (CI green, scheduled run 2026-11-09). **Branch:** `phase8/8a`, fast-forwarded to `main`
after CI passed on it. **Why 8A:** this file did not exist, so no 8A section was complete.

### 8A.0 / 8A.1 — context and owner answers
- Restored from STATUS, PROGRESS, ISSUES, both DECISIONS files, EVIDENCE, PHASE-07, the registry, README, results.md,
  the hosted-demo notes and the code. Known-stale items confirmed: README counts (419/205), results.md without the
  Phase 7 studies, NEXT_SESSION_PROMPT.md asking for Phase 7 and "do not begin Phase 8".
- Owner answers (private/owner-answers-8A.md; decisions D-100 … D-105): team of three, names only in the public
  repository; lecturer not asked yet; Week 6 more than a week away (no freeze this session); commits as the owner with no
  AI mention, AI-use statement in course documents as a draft for the owner; Marp decks; hosted database stays at 0010.
- Setup: `private/` ignored first and committed alone; the pack unzipped without overwriting; only its `docs/` files
  committed.

### 8A.2 — baseline (P8-E01)
pytest 511 passed / 6 skipped; ruff; contracts; web typecheck, lint, 24 unit tests, build; Playwright visual 42/42;
five projects 190 passed / 29 failed / 7 skipped — 28 of the failures are Firefox failing to start on this Mac
("Could not find profile folder", even launched by hand: ENV-P8-01), 1 an intermittent phone header-scroll check
(QA-P8-01); lab vitals 18/18 alone. The brief's expected "185 / 7" counted four projects (desktop, mobile, WebKit,
iPhone-sized WebKit); on those four the baseline was 190 passed, 1 failed (that intermittent check), 7 skipped.

### WP0 — what the hosted demo showed wrong (P8-E03 … P8-E06)
| Defect | Cause (label) | Fix | Test (failed before, passes after) |
|---|---|---|---|
| F1 3D floor dark in light theme | VERIFIED: `token()` read during render in a memo keyed on next-themes' `resolvedTheme`; next-themes sets the `<html>` class in its own effect, and under load the memo read the old theme first and never again. It reproduced both on first load (system dark, app light) and after a runtime switch, depending on load. The brief's rAF approach (`useChartTheme`, S17) still lost the race | `useChartTheme()` now changes when the class on `<html>` really changes (MutationObserver) and once on the first frame after mount; moved to `chart-theme.ts`; used by the 3D view and every chart | `e2e/theme.spec.ts` F1 on Overview and Inventory, Chromium and WebKit: floor pixel sampled against `--bg-deep` (before: rgb 9,16,18 in light theme) |
| F2 simulated data shown as green "available" | VERIFIED: the overview rendered only `status`; the API's `basis` was dropped | `CapabilityStatus`: status and basis together in the provenance colour ("available · simulated"); observed rows unchanged | `theme.spec.ts` F2 + 2 unit tests |
| F3 translucent legend over racks | VERIFIED: `bg-surface/90` overlay inside the canvas area | Legend is a footer below the view (same reserved height); hover card opaque; disabled toolbar buttons opaque with muted text (contrast ≥ 4.5:1 both themes) | `theme.spec.ts` F3 (alpha 0.9 and opacity 0.5 before) |
| F4 sweep | 15 screens × 1440/834/390 px × load light, load dark (opposite system scheme) and runtime switch, Chromium and WebKit: 174 states each, 96 charts, 16 3D checks, 0 problems after the fix | — | Two new screenshot baselines after a runtime switch (Overview, Inventory), darwin and linux; four desktop baselines changed with the legend (reviewed) |
| F5 hosted check | see "Push, deploy and hosted check" below | — | — |

### Push, deploy and hosted check (P8-E10 … P8-E13)
- CI on `phase8/8a` went green 8/8 (run 42772745703) after the Linux screenshots it recorded were reviewed and committed;
  `main` was then fast-forwarded and pushed (`9f8da12..e272204`); Vercel deployed `e272204` (deployment
  `dL4FU6xntDo5AdpYvuhNqKX1itvq`).
- **F5, read-only on the hosted demo** with the demo viewer account (Chromium and WebKit, both themes, system scheme
  opposite to the app theme, runtime switch both ways): the 3D floor follows the theme, capabilities show their basis,
  the legend is opaque, every chart follows the theme. Screenshots `docs/screenshots/phase8/hosted-e272204-*.png`.
- **Rehearsal:** the script's screens all load on the hosted demo (0.1–1.9 s each, warm); the two write steps (Start
  investigation, Approve) were not clicked on the public demo and were timed on the local stack instead (5.8 s). The
  spoken run-through against the time limit is the team's, once the limit is known.

### WP1 — documents (P8-E07)
README (counts, operations studies with the kind of every number, generation local only, n8n, ABC/XYZ, CO2 cap,
negative results, a source comment beside every number); results.md (eight new study sections); coverage.md (week →
study → screen → evidence → status, project only). InventoryBench: the score covers the 600 real-trajectory
instances its metrics.json records, not all 1,320 the benchmark holds (DOC-P8-01, fixed in P8-E18; IB-P8-01 open).

### WP2 — one source for numbers (P8-E08)
`scripts/course_metrics.py` → `docs/course/metrics.md` and `metrics.json` (15 current studies; superseded and
exploratory runs listed as not evidence). `tests/test_course_metrics.py` fails when a current run has no metrics.json, a
field is missing, the files are stale, or a course document quotes a bold number or headline that is not in metrics.md.

### WP9a — interim pack (P8-E09)
Drafts for the owner: `ai-use-statement.md`, `interim-deck.md` (Marp, 10 slides, D01 title), `demo-script-5min.md`,
`marker-guide.md`, `CONTRIBUTIONS.md` (names only). Results: S2 "accuracy ≠ value" (labelled exploratory, from
metrics.md's exploratory section, D-109), E1 and QC1, as the brief planned (STUDY-P8-02 fixed in P8-E18). Deck illustrations D01–D05 committed;
**D06 is truncated** (70.8 % of its pixel data, no end chunk) and not used (ART-P8-01). Not tagged `course-interim`:
the owner tags it at the start of the 48-hour freeze.

### Illustrations (owner request in this session; brief WP-ART, normally 8B)
Pull request https://github.com/krish2105/SupplyLens-/pull/16: A02, A13, A16 shown only in their briefed states; A17
and A18 prepared and rendered nowhere until their 8B screens exist; final-deck skeleton with D01–D05. **Approved by the
owner and merged on 2026-11-10 (D-108); deployed and checked on the hosted demo (P8-E16).** Review findings: content matches the briefs; subjects extend past the
middle 70 %; faint background-removal residue, not visible at 144 or 96 px on either theme.

### Sign-in illustration (owner screenshot, 2026-11-10, P8-E19)
The welcome art showed small in the lower right of its panel; it now fills the panel as a square crop of its subject,
centred, from a native-resolution file (FE-P8-04).

### Not done or blocked
- Lecturer's answers (8A.1b) not obtained; Week 6 date, limit and format unknown; deck length not yet checked against a
  limit. The AI-use statement is a draft. Teammates' consent to be named publicly and their AI tools: open.
- Playwright's Firefox does not start on macOS 27.2 (ENV-P8-01); locally it now runs in Playwright's Linux image
  (`scripts/e2e_firefox_docker.sh`), as in CI.
- 8B items found now: the study id "L1" is already used by the lead-time demand study in results.md, so the 8B ETA study
  needs another id (STUDY-P8-01).
