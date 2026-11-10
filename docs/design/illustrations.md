# Illustrations (asset pack A01–A18)

Sources: `design/source-assets/supplylens/` holds the 18 supplied PNGs byte-for-byte (SHA-256 checked against
`source_manifest.json` by the build script). They are never served.

Derivatives: `uv run python scripts/optimize_illustrations.py` writes lossless-alpha WebP files (2× the largest display
size: 1536 px wide (native) for A01, 360 px square for the rest) to `apps/web/public/illustrations/supplylens/` and the app
manifest `apps/web/lib/illustrations.json` (source hash, derivative hash, size, usage, review note, whether it is rendered).
Total ≈ 433 KB (433,260 bytes).

| ID | Shown in | Condition |
|---|---|---|
| A01 welcome | Sign-in page (≥768 px): a square crop of the subject fills the art panel | Sign-in only; an e2e test asserts it never appears on the populated overview |
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
| A02 import data *(Phase 8, owner-approved)* | Data admission | No admitted dataset **and** no import batch yet **and** the user is a tenant admin outside the locked public demo; the page waits for the role and the batch list, so the art never shows and then goes |
| A13 empty suppliers *(Phase 8, owner-approved)* | Supplier market | No award data imported **in the Contract research workspace**, the one that holds it; other workspaces keep the text and icon, because there the data exists elsewhere |
| A16 empty value study *(Phase 8, owner-approved)* | Value | The value ledger has no study; never over a populated ledger |
| A17 empty extraction *(Phase 8, owner-approved)* | Policies › document reader › Extracted terms | Only when the rules found no field in the version; never while loading or on errors (unit test: used only in `extracted-terms.tsx`) |
| A18 assistant ready *(Phase 8, owner-approved)* | Status assistant drawer | Only before the first question; never for answers, withheld answers or errors (unit test: used only in `status-assistant.tsx`) |

Phase 8 (2026-11-10): the owner supplied new **A02**, **A13** and **A16** for the Phase 8 briefs
(`docs/design/image-prompts-phase8.md`; the earlier files were withheld under D-040: document lines and a pie chart,
joined suppliers, kraft cartons) and new **A17**, **A18**. The owner approved them on 2026-11-10 by merging pull request #16
(D-108). Review findings, recorded per file in `source_manifest.json`
(`phase8_review`, `quality_notes`):
- Content matches each brief; no text, numbers, logos, people or charts.
- Framing: no subject stays inside the middle 70 % the brief asks for (nearest edge 29–74 px against 154 px). Shown with
  `object-contain`, so nothing is cut.
- Edge residue from background removal: 1,898–27,935 faint pixels outside each subject. Not visible at 144 px or 96 px
  on the light (#f4f8f6) or dark (#0d1517) background (2× pixel density review, 1440/834/390 px).
- A02 and A18 have one corner pixel at alpha 1 (the brief asks for 0); not visible.

Rules in code (`apps/web/components/illustration.tsx`): decorative only (`alt=""`, `aria-hidden`), semantic HTML
carries the title and actions, a failed image load collapses to nothing, and errors/loading never use empty-state art.
Reviewed in the running app in light and dark themes at 1440 px and 375 px (session-4 screenshots,
`docs/screenshots/session4/`).

Phase 4B review (2026-10-23, `docs/agent-handoff/phases/PHASE-04B.md` §4): the 13 published pieces match their states and
load in every capture (light and dark, 1440/834/390 px). A02, A13 and A16 stay withheld; on review they also show data,
stock or a network that the empty state does not have. Replacement is optional; exact briefs are in PHASE-04B §8 and
need owner approval before any image is produced. Art is never a substitute for charts, data or status.
