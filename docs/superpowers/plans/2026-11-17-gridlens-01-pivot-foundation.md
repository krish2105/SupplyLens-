# GridLens Plan 1 — Pivot foundation (rename and remove supply-chain-only features)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the SupplyLens repository into GridLens by name, and delete the supply-chain features that have no energy counterpart and no other code depending on them, with every remaining test still green.

**Architecture:** Mechanical rename first (packages, imports, environment prefix, database names, product name), proved by the unchanged test count. Then delete one self-contained feature slice per task (research studies, supplier market, n8n/HubSpot hand-offs, contract-research ingestion), each proved by the suite. The supply-chain core that the energy features will *repurpose* (approvals and actions, outbox and sandbox adapter, job worker, agent runs, inventory screens, database schema) is deliberately left for Plan 4, which swaps the domain model in one step.

**Tech Stack:** Python 3.12 (uv), FastAPI, PostgreSQL 17 + pgvector (Homebrew, local), Next.js 16 / TypeScript, Playwright, ruff, git.

**Spec:** `docs/superpowers/specs/2026-11-17-gridlens-design.md` (§3 renames, §11 keep/repurpose/delete).

## Global Constraints

- Names: `supplylens` → `gridlens`, `supplylens_ml` → `gridlens_ml`, `supplylens_opt` → `gridlens_opt`, `supplylens_worker` → `gridlens_worker`, environment prefix `SUPPLYLENS_` → `GRIDLENS_`, product name `SupplyLens` → `GridLens`.
- Never edit `docs/superpowers/**` with the rename (the spec and plans mention SupplyLens on purpose) and never touch the git tag `archive/supplylens`.
- Do not rename the hosted URL `supplylens-self.vercel.app` (in `.github/workflows/keep-warm.yml`); the owner renames the Vercel project, then that file changes.
- Every task ends with: `uv run ruff check .` clean, `uv run pytest -q` with 0 failures, and (for tasks touching `apps/web`) `npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test` clean.
- Work on branch `gridlens`. Commit after each task. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tables of deleted features stay in the database until Plan 4's new baseline migration; do not write new migrations in this plan.

## File map

| Path | Change |
|---|---|
| `services/api/src/supplylens/` → `services/api/src/gridlens/` | rename |
| `ml/supplylens_ml/` → `ml/gridlens_ml/` | rename |
| `optimisation/supplylens_opt/` → `optimisation/gridlens_opt/` | rename |
| `services/worker/src/supplylens_worker/` → `services/worker/src/gridlens_worker/` | rename |
| all code/config files | text rename (Task 2 command) |
| `evaluations/*_study.py` (supply-chain only), their tests and committed artifacts | delete (Task 3) |
| `services/api/src/gridlens/api/routes_market.py`, `ingest/world_bank.py`, `apps/web/app/(app)/market/` | delete (Task 4) |
| `infra/n8n/`, `assistant/handoff.py`, `scripts/smoke_investigation.py` | delete (Task 5) |
| `ingest/acord.py`, `ingest/cuad.py`, `knowledge/extract.py`, `components/extracted-terms.tsx` | delete (Task 6) |
| `README.md`, `PROJECT_STATUS.md`, `CONTRIBUTIONS.md`, `docs/course/genai-prompts.md` | rewrite / create (Task 7) |
| `execution_pack/`, `NEXT_SESSION.md`, `TASKS.md`, SupplyLens course decks | delete (Task 7) |

---

### Task 1: Record the baseline

**Files:** none changed.

- [ ] **Step 1: Make sure local databases exist and are migrated**

Run:
```bash
uv sync
chflags nohidden .venv/lib/python3.12/site-packages/*.pth   # see note below
uv run python -c "import supplylens, supplylens_ml, supplylens_opt; print('imports ok')"
./scripts/dev_db.sh
SUPPLYLENS_MIGRATION_URL=postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens_test \
  uv run alembic -c services/api/alembic.ini upgrade head
```
Expected: `imports ok`, `databases ready`, then Alembic upgrades or prints nothing (already at head).

Note (found on 2026-11-17): macOS marks the venv's editable-install file `_editable_impl_*.pth` as hidden, and Python
3.12.14 skips hidden `.pth` files, so `import supplylens` fails with `ModuleNotFoundError`. `chflags nohidden` fixes it;
repeat it after every `uv sync` that reinstalls the project.

- [ ] **Step 2: Run every check and write down the numbers**

Run:
```bash
uv run ruff check .
uv run pytest -q 2>&1 | tail -3
npm --prefix apps/web ci
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test 2>&1 | tail -5
```
Expected: ruff `All checks passed!`; pytest about `659 passed, 6 skipped` (README says 659/6). Record the exact pytest line as `BASELINE` — later tasks compare against it. If anything fails here, stop and report it: the failure predates this plan.

---

### Task 2: Mechanical rename to GridLens

**Files:**
- Rename: the four package directories in the file map
- Modify: every tracked code/config file containing the old names (generated by the command below)
- Modify: `scripts/dev_db.sh` (database and role names come with the text rename)

- [ ] **Step 1: Move the package directories with git**

```bash
git mv services/api/src/supplylens services/api/src/gridlens
git mv ml/supplylens_ml ml/gridlens_ml
git mv optimisation/supplylens_opt optimisation/gridlens_opt
git mv services/worker/src/supplylens_worker services/worker/src/gridlens_worker
```

- [ ] **Step 2: Rename text in code and config files**

```bash
git ls-files -z -- '*.py' '*.pyi' '*.ts' '*.tsx' '*.mts' '*.mjs' '*.js' '*.json' '*.toml' '*.yml' '*.yaml' \
  '*.sh' '*.ini' '*.mako' '*.sql' '*.css' '*.env.example' '.env.example' 'Dockerfile*' '**/Dockerfile*' \
  'docker-compose.yml' 'render.yaml' 'vercel.json' '.vercelignore' '.dockerignore' '.gitleaks.toml' \
  | grep -zv -e '^docs/superpowers/' -e '^uv.lock$' -e 'package-lock.json$' -e '^.github/workflows/keep-warm.yml$' \
  | xargs -0 perl -pi -e 's/supplylens_worker/gridlens_worker/g; s/supplylens_ml/gridlens_ml/g; s/supplylens_opt/gridlens_opt/g; s/SUPPLYLENS_/GRIDLENS_/g; s/SupplyLens/GridLens/g; s/SUPPLYLENS/GRIDLENS/g; s/supplylens/gridlens/g'
```
Then update the local, untracked `.env` the same way if it exists:
```bash
[ -f .env ] && perl -pi -e 's/SUPPLYLENS_/GRIDLENS_/g; s/supplylens/gridlens/g' .env || true
```

- [ ] **Step 3: Check that nothing outside the allowed places still says SupplyLens**

Run:
```bash
git grep -nIi supplylens -- . ':!docs' ':!*.md' ':!uv.lock' ':!**/package-lock.json' ':!.github/workflows/keep-warm.yml' ':!artifacts' | head
```
Expected: no output. Any hit is a file type the Step 2 glob missed: apply the same `perl` command to it.

- [ ] **Step 4: Refresh lock files**

```bash
uv lock
npm --prefix apps/web install --package-lock-only
git grep -n '"supplylens' apps/web/package-lock.json uv.lock | head -3
```
Expected: the last command prints nothing.

- [ ] **Step 5: Create the renamed databases and migrate the test database**

```bash
uv sync && chflags nohidden .venv/lib/python3.12/site-packages/*.pth
./scripts/dev_db.sh
GRIDLENS_MIGRATION_URL=postgresql+psycopg://gridlens_owner:gridlens_owner_dev@localhost:5432/gridlens_test \
  uv run alembic -c services/api/alembic.ini upgrade head
```
Expected: `databases ready`; Alembic upgrades 0001 → 0011 on the empty `gridlens_test`. (The old `supplylens*` databases stay; the owner may drop them later.)

- [ ] **Step 6: Run every check**

```bash
uv run python -c "import gridlens, gridlens_ml, gridlens_opt, gridlens_worker; print('imports ok')"
uv run ruff check .
uv run pytest -q 2>&1 | tail -3
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test 2>&1 | tail -5
```
Expected: ruff clean; pytest line identical to `BASELINE` (same passed and skipped counts). A failure here is a missed rename (for example a cookie or header name a test spells literally): fix the name, not the test's expectation of behaviour.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Rename SupplyLens to GridLens (packages, imports, env prefix, databases)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Remove the supply-chain research studies

Studies kept because later plans reuse their code: `fairness_study.py` (FA1 → FS1), `imbalance_study.py` (B1 → FS1), `redteam_study.py`, `redteam_cases.py`, `adversarial_child.py` (RED1 → CY1), `lstm_study.py`, `lstm_child.py` (LSTM model → GF1). Everything else in `evaluations/` is supply-chain only.

**Files:**
- Delete: `evaluations/{simulation,retrieval,eta,delay_risk,forecast_segments,agent,routing,assistant,leadtime_demand,maintenance,decision,answer_support,fuel,extraction,inventorybench,weather,emissions,generation,vision_qc,scheduling,forecast}_study.py`, `evaluations/r2_review_pack.py`
- Delete: `tests/test_{eta_study,fuel_study,routing_study,scheduling_study}.py`
- Delete: committed artifacts of deleted studies under `artifacts/experiments/`
- Modify: `evaluations/study_registry.json`, `scripts/course_metrics.py`, `docs/course/metrics.{md,json}`, `tests/test_course_metrics.py` (only if it names a deleted study)

- [ ] **Step 1: Delete the study scripts and their dedicated tests**

```bash
cd evaluations && git rm -q simulation_study.py retrieval_study.py eta_study.py delay_risk_study.py \
  forecast_segments_study.py agent_study.py routing_study.py assistant_study.py leadtime_demand_study.py \
  maintenance_study.py decision_study.py answer_support_study.py fuel_study.py extraction_study.py \
  inventorybench_study.py weather_study.py emissions_study.py generation_study.py vision_qc_study.py \
  scheduling_study.py forecast_study.py r2_review_pack.py && cd ..
git rm -q tests/test_eta_study.py tests/test_fuel_study.py tests/test_routing_study.py tests/test_scheduling_study.py
```

- [ ] **Step 2: Delete the committed artifacts of those studies**

The study ID prefixes that go are: `F1 F2 S1 S2 R1 R2 R3 C1 IB AGT E1 D1 W1 G1 JS1 PM1 QC1 FE1 ET1 RT1 X1 AS1`. Prefixes kept: `FA1 B1 RED1 W2`.
```bash
for p in F1 F2 S1 S2 R1 R2 R3 C1 IB AGT E1 D1 W1 G1 JS1 PM1 QC1 FE1 ET1 RT1 X1 AS1; do
  git ls-files "artifacts/experiments/${p}-*" | xargs -r git rm -q
done
git ls-files artifacts/experiments | cut -d/ -f3 | sort -u
```
Expected: only `B1-…`, `FA1-…`, `RED1-…`, `W2-…` directories remain.

- [ ] **Step 3: Remove the deleted runs from the study registry**

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path("evaluations/study_registry.json")
d = json.loads(p.read_text())
keep = ("FA1-", "B1-", "RED1-", "W2-")
d["experiments"] = {k: v for k, v in d["experiments"].items() if k.startswith(keep)}
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
print(sorted(d["experiments"]))
PY
```
Expected: only FA1, B1, RED1 and W2 run IDs printed.

- [ ] **Step 4: Remove deleted studies from `scripts/course_metrics.py`**

In `scripts/course_metrics.py` delete every dictionary entry whose key is one of the deleted prefixes (in `DATA_KIND` and in every other per-study dictionary in that file, for example the `("products", "cohort_size")` table and the headline-fields table). Keep the `FA1`, `B1`, `RED1`, `W2` entries. Then regenerate:
```bash
uv run python scripts/course_metrics.py
uv run python scripts/course_metrics.py --check && echo fresh
```
Expected: `fresh`.

- [ ] **Step 5: Find any remaining reference to a deleted study module**

```bash
git grep -nE "(simulation|retrieval|eta|delay_risk|forecast_segments|agent|routing|assistant|leadtime_demand|maintenance|decision|answer_support|fuel|extraction|inventorybench|weather|emissions|generation|vision_qc|scheduling|forecast)_study|r2_review_pack" -- '*.py' '*.sh' '*.yml' '*.toml' '*.json' ':!artifacts'
```
Expected: no output. For each hit, remove the import/call. If a hit is a test that exercises a deleted study, delete that test function (not the whole file unless every test in it is about deleted studies).

- [ ] **Step 6: Run the checks**

```bash
uv run ruff check . && uv run pytest -q 2>&1 | tail -3
```
Expected: 0 failures; passed count = `BASELINE` minus the deleted tests.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Remove supply-chain research studies; keep FA1, B1, RED1 and W2 code for reuse

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Remove the supplier market slice (World Bank awards)

**Files:**
- Delete: `services/api/src/gridlens/api/routes_market.py`, `services/api/src/gridlens/ingest/world_bank.py`, `apps/web/app/(app)/market/page.tsx`
- Modify: `services/api/src/gridlens/api/app.py`, `services/api/src/gridlens/api/schemas.py`, `apps/web/app/(app)/layout.tsx`, `apps/web/app/(app)/page.tsx`, `apps/web/lib/nav.ts` (if it lists Market), `scripts/download_datasets.py`, `scripts/test_data_tools.py`, `data/source_manifest.json`, `scripts/backup_restore_drill.sh`, `tests/test_contract_responses.py`, `tests/test_phase4b.py`, `apps/web/e2e/{illustrations,layout,ui-quality,visual}.spec.ts`, `apps/web/scripts/{capture-screens,screenshots}.mjs`, `packages/contracts/*` (regenerated)

- [ ] **Step 1: Write the failing test that the market API is gone**

Add to `tests/test_api.py`:
```python
def test_market_endpoints_removed(client):
    for path in ("/api/v1/market/summary", "/api/v1/market/suppliers"):
        assert client.get(path).status_code == 404
```
Check the fixture name and URL prefix used by the other tests in `tests/test_api.py` (look for how they call `/api/v1/...`) and use the same ones.

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_api.py::test_market_endpoints_removed -q`
Expected: FAIL (status 401/403/200, not 404) because the router is still mounted.

- [ ] **Step 3: Delete the backend slice**

```bash
git rm -q services/api/src/gridlens/api/routes_market.py services/api/src/gridlens/ingest/world_bank.py
```
In `services/api/src/gridlens/api/app.py` remove `routes_market` from the `from . import (...)` list and delete the line `app.include_router(routes_market.router)`.
In `services/api/src/gridlens/api/schemas.py` delete the classes `MarketSummary`, `SupplierHit`, `SupplierDetail` and any class used only by them (check with `git grep -n "<ClassName>"` before deleting each helper class).
In `scripts/download_datasets.py`, `scripts/test_data_tools.py` and `data/source_manifest.json` delete the World Bank dataset entry. In `scripts/backup_restore_drill.sh` delete `public_awards` from the table list it checks.

- [ ] **Step 4: Run the test to see it pass, then the backend suite**

```bash
uv run pytest tests/test_api.py::test_market_endpoints_removed -q
uv run pytest -q 2>&1 | tail -3
```
Expected: the new test passes. Other failures will name the market (in `test_contract_responses.py`, `test_phase4b.py`): delete those test functions or the market rows of their parameter lists.

- [ ] **Step 5: Regenerate the API contract**

```bash
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
```
Expected: the contract check passes; `packages/contracts/openapi.json` no longer contains `/market`.

- [ ] **Step 6: Delete the web screen and its links**

```bash
git rm -q -r "apps/web/app/(app)/market"
git grep -n -i "market" -- apps/web ':!apps/web/package-lock.json'
```
Remove each remaining link, nav entry, screenshot entry and e2e case that points to `/market` or the Market screen (in `layout.tsx`, `page.tsx`, `lib/nav.ts`, the four e2e specs and two screenshot scripts). Leave words like "market" that are not about this screen.

- [ ] **Step 7: Run web checks**

```bash
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test
(cd apps/web && npx playwright test --project desktop --grep-invert visual 2>&1 | tail -3)
```
Expected: all pass. (Visual snapshot baselines will be rebuilt in Plan 4; if a visual test fails only because the Market screenshot is missing, remove that case.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Remove the supplier market screen, API and World Bank ingest

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Remove the n8n workflows, the HubSpot hand-off and the investigation smoke script

The procurement investigator (`agent/graph.py`, `agent_runs`) is *not* removed here: jobs, alerts, admission and the worker depend on it, and Plan 4 replaces it with replay sessions.

**Files:**
- Delete: `infra/n8n/`, `services/api/src/gridlens/assistant/handoff.py`, `scripts/smoke_investigation.py`
- Modify: `services/api/src/gridlens/assistant/__init__.py`, `services/api/src/gridlens/api/routes_assistant.py`, `services/api/src/gridlens/api/schemas.py` (`AssistantHandoff`), `apps/web/components/status-assistant.tsx`, `apps/web/e2e/assistant.spec.ts`, `tests/test_assistant.py`, `README.md` mentions handled in Task 7

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assistant.py`:
```python
def test_handoff_endpoint_removed(client):
    assert client.post("/api/v1/assistant/handoff", json={}).status_code in (404, 405)
```
Use the same client fixture and CSRF/sign-in helpers as the neighbouring tests in that file (copy how they post to `/assistant/ask`).

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_assistant.py::test_handoff_endpoint_removed -q`
Expected: FAIL (the route exists).

- [ ] **Step 3: Delete the hand-off**

```bash
git rm -q -r infra/n8n services/api/src/gridlens/assistant/handoff.py scripts/smoke_investigation.py
```
In `routes_assistant.py` delete the `@router.post("/handoff", ...)` function and the `handoff` import. In `assistant/__init__.py` remove any `handoff` export. In `schemas.py` delete `AssistantHandoff`. Delete the hand-off tests in `tests/test_assistant.py` (the functions that call `/handoff` or import `handoff`), keep the new one. In `apps/web/components/status-assistant.tsx` remove the HubSpot hand-off button and its request; in `apps/web/e2e/assistant.spec.ts` remove the hand-off case.

- [ ] **Step 4: Check for leftovers and run everything**

```bash
git grep -nE "handoff|hubspot|HubSpot|n8n" -- ':!docs' ':!*.md' ':!artifacts' ':!**/package-lock.json'
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
uv run ruff check . && uv run pytest -q 2>&1 | tail -3
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test
```
Expected: grep prints nothing; all checks pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Remove n8n workflows, HubSpot hand-off and the investigation smoke script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Remove contract-research ingestion and term extraction (ACORD, CUAD, clause labels)

The retrieval engine (`knowledge/retrieve.py`, `rerank.py`, `embed.py`, `ingest.py`, `upload.py`, `acl.py`, `generate.py`) stays: Plan 4 points it at tariff, policy and grid-code documents.

**Files:**
- Delete: `services/api/src/gridlens/ingest/acord.py`, `services/api/src/gridlens/ingest/cuad.py`, `services/api/src/gridlens/knowledge/extract.py`, `apps/web/components/extracted-terms.tsx`, `apps/web/e2e/extraction.spec.ts`, `tests/test_extraction.py`
- Modify: `services/api/src/gridlens/api/routes_decisions.py` (extracted-terms endpoint), `services/api/src/gridlens/api/routes_ops.py` (clause-labels endpoint), `services/api/src/gridlens/api/schemas.py`, `services/api/src/gridlens/seed.py`, `apps/web/app/(app)/policies/page.tsx`, `apps/web/app/(app)/research/page.tsx`, `apps/web/app/(app)/page.tsx`, `apps/web/components/illustration.test.ts`, `apps/web/e2e/{visual,workflows}.spec.ts`, `scripts/download_datasets.py`, `data/source_manifest.json`, `scripts/backup_restore_drill.sh`, `tests/test_contract_responses.py`, `tests/test_remediation.py`, `docs/remediation/register.json`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py`:
```python
def test_contract_research_endpoints_removed(client):
    vid = "00000000-0000-0000-0000-000000000000"
    for path in (f"/api/v1/documents/versions/{vid}/extracted-terms", f"/api/v1/documents/versions/{vid}/labels"):
        assert client.get(path).status_code == 404
```
(Use the same fixture and sign-in pattern as Task 4's test.) Note: the 404 must come from the route being absent. If the signed-in route returns 404 for an unknown version today, first confirm the test fails by checking the route still answers with another status for a signed-out request; if it cannot be made to fail, assert instead that the paths are absent from `app.openapi()["paths"]`:
```python
def test_contract_research_routes_absent():
    from gridlens.api.app import app
    paths = app.openapi()["paths"]
    assert not any(p.endswith("/extracted-terms") or p.endswith("/labels") for p in paths)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_api.py -k contract_research -q`
Expected: FAIL.

- [ ] **Step 3: Delete backend pieces**

```bash
git rm -q services/api/src/gridlens/ingest/acord.py services/api/src/gridlens/ingest/cuad.py \
  services/api/src/gridlens/knowledge/extract.py tests/test_extraction.py
```
In `routes_decisions.py` delete the `extracted-terms` endpoint function and the imports `EXTRACTOR_VERSION`, `extract as extract_terms`. In `routes_ops.py` delete the `/documents/versions/{version_id}/labels` endpoint. In `schemas.py` delete `ExtractedTerms`, `ClauseLabel` and helpers only they use. In `seed.py` delete the ACORD/CUAD workspace or document seeding (keep tenants and users). In `scripts/download_datasets.py` and `data/source_manifest.json` delete the ACORD and CUAD entries; in `scripts/backup_restore_drill.sh` delete `clause_labels` from its checks. In `docs/remediation/register.json` leave historical entries untouched unless a test (`tests/test_remediation.py`) imports a deleted module; then delete only that test case.

- [ ] **Step 4: Run backend checks**

```bash
git grep -nE "acord|cuad|ACORD|CUAD|clause_labels|extracted.terms|knowledge\.extract" -- '*.py' '*.sh' '*.json' ':!artifacts' ':!docs' ':!**/package-lock.json' ':!services/api/migrations'
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
uv run ruff check . && uv run pytest -q 2>&1 | tail -3
```
Expected: grep prints nothing (old migrations may mention `clause_labels`; they are excluded and replaced in Plan 4); all tests pass, including the new one.

- [ ] **Step 5: Delete web pieces**

```bash
git rm -q apps/web/components/extracted-terms.tsx apps/web/e2e/extraction.spec.ts
git grep -nE "extracted-terms|ExtractedTerms|extraction" -- apps/web ':!apps/web/package-lock.json'
```
Remove each hit (the Policies › Extracted terms tab, research page section links, illustration test entry, visual/workflow e2e cases).

- [ ] **Step 6: Run web checks**

```bash
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Remove ACORD/CUAD ingestion, clause labels and contract-term extraction

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: GridLens project documents and team record

**Files:**
- Rewrite: `README.md`, `PROJECT_STATUS.md`, `CONTRIBUTIONS.md`
- Create: `docs/course/genai-prompts.md`
- Delete: `execution_pack/`, `NEXT_SESSION.md`, `TASKS.md`, `docs/course/{interim-deck,final-deck,demo-script-5min,marker-guide,case-links,coverage,outline-check}.md`
- Keep: `DECISIONS.md`, `EVIDENCE_INDEX.md`, `docs/operations/`, `docs/security/` (platform history, still true after the rename)

- [ ] **Step 1: Delete SupplyLens-only documents**

```bash
git rm -q -r execution_pack NEXT_SESSION.md TASKS.md
cd docs/course && git rm -q interim-deck.md final-deck.md demo-script-5min.md marker-guide.md case-links.md coverage.md outline-check.md && cd ../..
git grep -nE "interim-deck|final-deck|demo-script-5min|marker-guide|case-links|outline-check|execution_pack|NEXT_SESSION|TASKS\.md" -- ':!docs/superpowers'
```
Remove or reword each hit (links in other documents). If `tests/test_course_metrics.py` or `scripts/course_metrics.py` read a deleted file, remove that read.

- [ ] **Step 2: Write `README.md`**

Replace the file with:
````markdown
<div align="center">

# GridLens

**AI energy management for industrial-park microgrids**

15-minute load and solar forecasts · deep reinforcement learning (PPO, SAC) and stochastic MPC dispatch ·
diesel unit commitment · islanded resilience with frequency and load-shedding · a live EMS dashboard

</div>

## The challenge

An industrial park runs a semi-autonomous microgrid: rooftop solar, a battery energy storage system (BESS), backup diesel
generators and a grid connection. Variable solar output, peak-time tariffs and sudden machine load spikes make energy
expensive and power quality unstable. GridLens forecasts supply and demand, schedules the battery, the grid and flexible
machine loads, commits the diesel units, and keeps the park running when the grid fails, while showing every decision
and who was asked to give up power and why.

Group 2 final project for *AI in Operations* (Dr Sandip Kumar Roy), S P Jain, Dubai. Design:
[`docs/superpowers/specs/2026-11-17-gridlens-design.md`](docs/superpowers/specs/2026-11-17-gridlens-design.md).

## Status

Pivot in progress from SupplyLens (preserved at git tag `archive/supplylens`). Plans and progress:
[`docs/superpowers/plans/`](docs/superpowers/plans/). No result in this README is final until a study artifact backs it.

## Pipeline

```
data ingestion → ML inference (forecasts) → optimisation (unit commitment, MPC, RL) → simulation (MicrogridEnv) → REST API / EMS dashboard
```

## Data

| Data | Source | Label |
|---|---|---|
| 15-minute industrial load, 2018 | UCI Steel Industry Energy Consumption (id 851), CC BY 4.0 | Observed |
| Weather and irradiance, 2018 | Open-Meteo historical archive, CC BY 4.0 | Observed |
| Solar output | pvlib model from observed weather | Simulated |
| Tariffs | KEPCO industrial time-of-use (Korea); ADDC 2025 industrial (UAE what-if) | Observed or marked assumed |
| Tenants, production schedules, flexible loads | generated | Simulated |

## Getting started

Requirements: PostgreSQL 17 with pgvector, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env && ./scripts/dev_db.sh && uv sync
uv run alembic -c services/api/alembic.ini upgrade head
uv run uvicorn gridlens.api.app:app --port 8000
npm --prefix apps/web install && npm --prefix apps/web run dev   # http://localhost:3100
```

## Team

See [`CONTRIBUTIONS.md`](CONTRIBUTIONS.md). GenAI use: [`docs/course/genai-prompts.md`](docs/course/genai-prompts.md)
and [`docs/course/ai-use-statement.md`](docs/course/ai-use-statement.md).

## Acknowledgements

UCI Steel Industry Energy Consumption (Sathishkumar V E, Changsun Shin and Youngyun Cho; doi:10.24432/C52G8C);
Open-Meteo; pvlib. Public datasets are used under CC BY 4.0 with attribution.
````

- [ ] **Step 3: Write `CONTRIBUTIONS.md`**

Replace the file with:
```markdown
# Contributions

Group 2 final project, *AI in Operations*, S P Jain, Dubai. Seven members.

## Team

| # | Name |
|---|---|
| 1 | Krishna Mathur |
| 2 | Atharva Soundankar |
| 3 | Yash Petkar |
| 4 | Member 4 (name to be added) |
| 5 | Member 5 (name to be added) |
| 6 | Member 6 (name to be added) |
| 7 | Member 7 (name to be added) |

## Ownership (proposed in docs/TEAM_PLAN.md; the team confirms each row and dates it)

| Area | Owner | Packages / documents | Agreed (date) |
|---|---|---|---|
| Project lead, platform and integration | Krishna Mathur | Plan 1, Plan 4 T1–T6 and T11 | |
| Data and forecasting | Atharva Soundankar | `ml/`, ingestion, GF1 (Plan 2 T1–T3, T11–T12; Plan 3 T7; Plan 5 T3) | |
| Simulator and resilience | Yash Petkar | `sim/` (Plan 2 T4–T9; Plan 3 T1–T3; Plan 5 T4, FS1) | |
| Deep RL (PPO, SAC) | Member 4 | `control/` RL (Plan 3 T8–T9) | |
| Stochastic MPC and unit commitment | Member 5 | `optimisation/`, `control/mpc.py` (Plan 2 T10; Plan 3 T4–T6, T11; Plan 5 T6) | |
| EMS dashboard and user experience | Member 6 | `apps/web` (Plan 3 T10; Plan 4 T7–T10) | |
| Evaluation, ethics and report lead | Member 7 | `evaluations/`, CY1, course pack (Plan 2 T13; Plan 5 T1–T2, T5, T7) | |

## Meeting log

| Date | Present | Decisions | Actions (who, by when) |
|---|---|---|---|
| | | | |
```

- [ ] **Step 4: Write `PROJECT_STATUS.md`**

Replace the file with:
```markdown
# GridLens project status

**Updated:** 2026-11-17 · **Branch:** `gridlens`

GridLens is the Group 2 final project (Intelligent Microgrid Energy Dispatch & Demand Response for Smart Industrial
Parks). It repurposes the SupplyLens platform, preserved at tag `archive/supplylens`.

| Plan | Scope | State |
|---|---|---|
| 1 | Pivot foundation: rename, remove supply-chain-only features | done when this file is committed |
| 2 | Energy core: data, forecasting, simulator, baselines | not started |
| 3 | Optimisation and RL controllers | not started |
| 4 | Domain swap in API, database and dashboard | not started |
| 5 | Studies, ethics and course deliverables | not started |

Presentation: 9 February 2027, 09:30 (40 minutes per group plus peer Q&A); Blackboard submission by 23:59.
```

- [ ] **Step 5: Create `docs/course/genai-prompts.md`**

```markdown
# GenAI prompt log

Dr Roy's requirement (Session III, slide 20): content generated with GenAI is encircled in the deck and report, and the
prompts are shared separately. This file is that separate record. Add a row for every prompt whose output went into the
project (code, text, figures, data), in time order.

| Date | Tool and model | Who | Prompt (verbatim or file link) | What it produced | Where it is used |
|---|---|---|---|---|---|
| 2026-11-17 | Claude Code, Claude Opus 5.5 | Krishna Mathur | Group 2 brief (slides 19, 20, 22) with "read all attachments, brainstorm, research, update files, ask me questions" | design spec and implementation plans | `docs/superpowers/` |
```

- [ ] **Step 6: Run checks and commit**

```bash
uv run ruff check . && uv run pytest -q 2>&1 | tail -3
uv run python scripts/course_metrics.py --check && echo fresh
git add -A
git commit -m "GridLens README, status, seven-member contributions record and GenAI prompt log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: checks pass, `fresh`.

---

## Done when

- `git grep -nIi supplylens -- . ':!docs' ':!*.md' ':!uv.lock' ':!**/package-lock.json' ':!.github/workflows/keep-warm.yml' ':!artifacts'` prints nothing.
- `uv run ruff check .`, `uv run pytest -q`, web typecheck, lint and unit tests pass.
- Market, n8n/HubSpot hand-off, ACORD/CUAD and supply-chain studies are gone; FA1, B1, RED1 and W2 code remains.
