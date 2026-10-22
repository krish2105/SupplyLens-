# Next session

Start from `main` after the session-4 commits. Read `PROJECT_STATUS.md` (state and last verified commands),
`docs/remediation/REGISTER.md` (22 audit findings, fixed / partially fixed / open) and `DECISIONS.md` D-037 … D-049.

## Run it
```bash
uv sync && (cd apps/web && npm ci)
SUPPLYLENS_MIGRATION_URL=postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens \
  uv run alembic -c services/api/alembic.ini upgrade head           # now at 0007
uv run uvicorn supplylens.api.app:app --port 8000                     # API
uv run python -m supplylens_worker.main                              # worker
(cd apps/web && npm run dev)                                         # web on :3100
docker compose --profile identity up -d keycloak                     # optional: OIDC on :8180 (infra/keycloak/README.md)
```
Keycloak needs about 700 MB of the Docker VM; on a 2 GB Colima VM run it with a small heap
(`JAVA_OPTS_KC_HEAP="-Xms128m -Xmx384m"`), as the session-4 tests did.

## Open work, in priority order
1. **S17 rest:** chart theme refresh after zoom/selection, 200 % zoom, WebGL context-loss tests (UX-010).
2. **S15 rest:** apply the decision-context fingerprint used by the scenario studio to the forecast lab, approvals
   drawer and exports.
3. **S19:** link each acceptance row to an immutable CI artifact automatically (acceptance register `evidence` column).
4. **Research:** a confirmatory forecast test needs data no protocol has looked at (UCI has none left, D-042); have the
   50-question R2 review sheet reviewed by a person; validate the lead-time-demand model on real windows.
5. **SKU-location planning** (D-043) before multiple warehouses; receipt feed from an ERP instead of manual booking.
6. **Corporate identity:** qualify OIDC against the customer's IdP (BUS-012, BUS-022 remain partial until then).
7. **ERP connector** (EXE-013, BUS-013): blocked on sandbox credentials from the owner.

## Things that are easy to get wrong
- Never mention any AI assistant in commits or files (owner instruction). Commit as
  `Krishna Mathur <113384784+krish2105@users.noreply.github.com>`.
- `SupplyLens_Updated_Pack_With_Images/` is reference material, git-ignored; source art lives in
  `design/source-assets/supplylens/`, web derivatives come only from `scripts/optimize_illustrations.py`.
- The e2e suite releases open Demo orders in `e2e/global-setup.ts`; without that the reference case is already covered
  by earlier test orders (S12 working as intended).
- Run Playwright against a production build (`NEXT_DIST_DIR=.next-build npx next build && npx next start --port 3101`);
  the dev server fails timing checks.
- The PITR drill on macOS needs `LC_ALL=en_US.UTF-8 TMPDIR=/tmp ./scripts/pitr_drill.sh` (postmaster refuses an unset
  locale; long temp paths break the socket path).
- Generative inference stays disabled unless the owner changes D-041.
