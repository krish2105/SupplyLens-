# Illustrations (asset pack A01–A16)

Sources: `design/source-assets/supplylens/` holds the 16 supplied PNGs byte-for-byte (SHA-256 checked against
`source_manifest.json` by the build script). They are never served.

Derivatives: `uv run python scripts/optimize_illustrations.py` writes lossless-alpha WebP files (2× the largest display
size: 1120 px wide for A01, 360 px square for the rest) to `apps/web/public/illustrations/supplylens/` and the app
manifest `apps/web/lib/illustrations.json` (source hash, derivative hash, size, usage, review note). Total ≈ 290 KB.

| ID | Shown in | Condition |
|---|---|---|
| A01 welcome | Sign-in page (≥768 px) | Sign-in only; an e2e test asserts it never appears on the populated overview |
| A03 empty inventory | Inventory, overview 3D panel | Successful response with no stock records (copy says missing records are not zero stock) |
| A04 empty evidence | Policies | Library returns no documents the reader may see |
| A05 forecast setup | Forecast lab | History exists but no forecast run for the product/origin/model |
| A06 empty scenarios | Scenario studio | No saved scenario runs |
| A07 no results | Inventory, exceptions | Filters exclude every row of a non-empty result |
| A08 no pending work | Approvals, exceptions | Zero items in the visible queue (copy says it is not system health) |
| A09 connection paused | Any `ErrorState` | `fetch` got no response (offline); retry offered, input kept |
| A10 restricted access | Any `ErrorState` | Server answered 403 |
| A11 empty integrations | Settings › Connections | No live ERP connector configured (BC/SAP are not implemented) |
| A12 policy change | Policies | At least one document version supersedes another |
| A14 empty research | Research study cards | No experiment recorded for that study |
| A15 decision history | Investigations | No runs in the workspace |

Not published (owner decision D-040): **A02** import data (document lines and a pie chart instead of a blank sheet),
**A13** empty suppliers (joined suppliers instead of unjoined connectors), **A16** value study (kraft cartons read as a
value signal). Their states use text with an icon.

Rules in code (`apps/web/components/illustration.tsx`): decorative only (`alt=""`, `aria-hidden`), semantic HTML
carries the title and actions, a failed image load collapses to nothing, and errors/loading never use empty-state art.
Reviewed in the running app in light and dark themes at 1440 px and 375 px (session-4 screenshots,
`docs/screenshots/session4/`).

Phase 4B review (2026-10-23, `docs/agent-handoff/phases/PHASE-04B.md` §4): the 13 published pieces match their states and
load in every capture (light and dark, 1440/834/390 px). A02, A13 and A16 stay withheld; on review they also show data,
stock or a network that the empty state does not have. Replacement is optional; exact briefs are in PHASE-04B §8 and
need owner approval before any image is produced. Art is never a substitute for charts, data or status.
