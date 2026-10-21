# SupplyLens tasks

States: planned · active · implemented · verified · blocked. "Verified" = a command in EVIDENCE_INDEX.md ran and
passed locally. The per-requirement status lives in `docs/acceptance/acceptance_register.csv` (80 items).

## Done this far (verified)
| Epic | Delivered | Evidence |
|---|---|---|
| DATA | UCI ingestion + reconciliation; ACORD, CUAD, World Bank, InventoryBench admitted with hashes | E-01, E-02, E-14..E-16 |
| FCST | Frozen F1 study; LightGBM + quantile TCN trained, registered, served with hash checks and replay guard | E-13, E-17 |
| PLAN | CP-SAT planner + validator + temporal terms; S1 simulation; q90 replenishment basis | E-04, E-18 |
| KNOW | Hybrid temporal retrieval; R1/R2/C1 studies; expert clause labels; abstention | E-19 |
| AGENT/ACT | Deterministic LangGraph investigator; approvals, outbox, sandbox ERP, reconciliation; AGT study | E-05, E-06, E-20 |
| SEC | Forced RLS (30 tables); 64-case denial matrix; CSRF; idempotency; rate limits | E-08, E-21 |
| UX | 15 screens, ⌘K palette, linked 3D/2D/table, themes; 37 Playwright tests incl. axe light/dark/mobile | E-07, E-22 |
| OPS | OpenAPI + TS types drift check; backup/restore drill; Dockerfiles, Compose, CI workflow | E-23, E-24 |
| VALUE | Value ledger from simulated studies with evidence classes; research report; model/data cards | docs/research |

## Next (planned)
| Task | Req IDs | Notes |
|---|---|---|
| Full `docker compose up` run | ARC-01, EXE-001 | needs a bigger colima VM |
| Run CI on GitHub | ARC-02, ARC-08 | needs a remote (owner approval) |
| Lead-time aggregate demand model | ML-005, ML-007 | replaces summed-q90 heuristic |
| Cross-encoder reranker condition; human review of R2 sample | ARC-04, ML-006 | |
| Load test on reference profile | ARC-07, BUS-015 | |
| WebGL-failure e2e; Web Vitals; manual screen reader | EXE-010, UX-010, UX-011 | |
| Migrate web client to generated contract types | ARC-02 | types exist in packages/contracts |
| OpenTelemetry exporter | ARC (observability) | trace ids + logs only today |

## Blocked
| Task | Req IDs | Needs |
|---|---|---|
| OIDC sign-in, SCIM lifecycle | BUS-012, BUS-022 | identity provider |
| Real ERP sandbox connector | BUS-013, EXE-013 | buyer sandbox + credentials |
| Pilot, user studies, scorecard | BUS-016, BUS-017 | business users |
| LLM agent ablation | ML-006 | owner chose no generative LLM |
| M5 study | DAT-004 | owner acceptance of Kaggle rules |

## Known defects
| ID | Severity | Description | State |
|---|---|---|---|
| DEF-01 | — | drei `Html` unmount crash | fixed (DOM overlay), verified E-22 |
| DEF-02 | medium | Idempotency key check not atomic under concurrent identical requests (state guards still prevent double approval) | open |
| DEF-03 | low | Rate limits are per process | open (documented) |
| DEF-04 | low | One ACORD test query excluded due to source quoting mismatch | open (documented) |
