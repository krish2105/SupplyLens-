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
1. **Overview mobile LCP** (2.76 s throttled; target 2.5 s): the headline needs two API responses after hydration;
   consider rendering it on the server or shipping less JavaScript on `/`.
2. **Manual screen-reader pass** (UX-010) and **human review** of the 50-question R2 sheet (ARC-04).
3. **Load test on the declared 8 vCPU / 32 GiB profile** (ARC-07); back-pressure is in place.
4. **Corporate identity provider** (BUS-012/022) and an **ERP sandbox** (EXE-013, BUS-013): need outside parties.
5. **Confirmatory forecast test** on data no protocol has seen (D-042).

## Hosted demo
https://supplylens-self.vercel.app — rebuild and redeploy steps in `docs/operations/hosted-demo.md`. After code changes:
`uv run python scripts/vercel/build_api.py --storage build/hosted-storage && vercel deploy --prod`.

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
