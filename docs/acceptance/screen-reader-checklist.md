# Screen-reader pass (UX-010) — checklist for a human tester

**Status: automated structure checks pass; the manual assistive-technology pass has NOT been done.**
Nothing in this repository has been tested with NVDA, JAWS, VoiceOver or TalkBack. An engineer cannot sign this
off from a headless browser: the automated suite proves landmarks, names and keyboard behaviour exist, not that the
experience is understandable when spoken.

## What is already checked automatically (`apps/web/e2e/a11y.spec.ts`, desktop and mobile projects)

| Check | Screens |
|---|---|
| exactly one `main`; one navigation landmark per viewport (`Primary` on desktop, `Sections` on mobile) | all 13 |
| exactly one `h1`; heading levels never skip downward | all 13 |
| every visible form control has an accessible name | all 13 |
| every visible table has a caption or name; images/canvases have a text alternative or are hidden | all 13 |
| connection status live region present | all 13 |
| skip link is the first tab stop and moves focus to `#main`; first 30 tab stops each show a focus indicator | exceptions |
| command palette: Ctrl+K opens, focus is trapped, Escape closes and returns focus (desktop only: the button is hidden on narrow screens) | exceptions |
| approval can be decided with the keyboard alone | approvals |
| run progress and errors use live regions | runs |
| no horizontal scroll at 200% zoom-equivalent width | exceptions |

The accessibility tree of each screen is saved to `artifacts/reports/a11y-tree/<screen>.yml` on every desktop run, so a
reviewer can read what a screen reader is given without running the app.

## Known gaps the tester should look at first

1. **3D warehouse view** (`/inventory`): the canvas has a text summary; check it is enough to act on, and that the
   table alternative carries the same information.
2. **Charts** (ECharts canvas): each has an `aria-label` with a summary sentence; check the summary states the trend,
   not just "line chart".
3. **Command palette on touch / small screens**: the button is hidden below the `md` breakpoint; Ctrl+K is the only
   entry. The `Sections` strip is the substitute. Confirm that is acceptable.
4. **Mobile LCP** is above the 2.5 s field target on throttled mobile (see `docs/operations/web-vitals.md`).

## Procedure (about 90 minutes)

Use at least one desktop reader (NVDA + Firefox or Chrome on Windows, or VoiceOver + Safari on macOS) and one mobile
reader (VoiceOver on iOS or TalkBack on Android). Sign in as each dev role; the roles see different screens.

For every screen below, record PASS / FAIL / NOTE in `docs/acceptance/screen-reader-results.csv`
(columns: `date, tester, reader, browser, screen, result, note`).

| Screen | Task to perform with the reader only |
|---|---|
| Overview | Find the headline numbers and say which are real, simulated or generated |
| Exceptions | Hear the highest-severity exception, its value and deadline; acknowledge an alert |
| Inventory | Find a SKU, hear its cover and position; reach the table alternative to the 3D view |
| Forecast | Hear the forecast interval and what basis (model/run) produced it |
| Scenarios | Change one assumption, run it, and hear the result and the difference from baseline |
| Runs | Start a run; hear that it is in progress and when it finishes or fails |
| Approvals | Open a draft, hear the evidence, approve or reject it, hear the outcome |
| Policies | Compare two versions of a policy and hear what changed |
| Research / Value / Data / Admin / Settings | Reach every region by landmark or heading navigation |

Fail a screen if: a control is announced without a name or role; an update (success, error, progress) is silent; focus
is lost after an action or dialog; a table cannot be navigated by cell; colour is the only carrier of a status.

Record the result in `docs/acceptance/acceptance_register.csv` row **UX-010** only after the CSV above is filled in.
