# SupplyLens tasks

States: planned · active · implemented · verified · blocked. "Verified" = a command in EVIDENCE_INDEX.md ran and
passed locally. The per-requirement status lives in `docs/acceptance/acceptance_register.csv` (80 items).

## Done this far (verified)
| Epic | Delivered | Evidence |
|---|---|---|
| DATA | UCI ingestion + reconciliation; ACORD, CUAD, World Bank, InventoryBench admitted with hashes | E-01, E-02, E-14..E-16 |
| FCST | Frozen F1 study; LightGBM + quantile TCN trained, registered, served with hash checks and replay guard | E-13, E-17 |
| PLAN | CP-SAT planner + validator + temporal terms; S1 simulation; lead-time-demand replenishment basis (was summed q90) | E-04, E-18, E-31 |
| KNOW | Hybrid temporal retrieval; R1/R2/C1 studies; expert clause labels; abstention | E-19 |
| AGENT/ACT | Deterministic LangGraph investigator; approvals, outbox, sandbox ERP, reconciliation; AGT study | E-05, E-06, E-20 |
| SEC | Forced RLS (30 tables); 64-case denial matrix; CSRF; idempotency; rate limits | E-08, E-21 |
| UX | 15 screens, ⌘K palette, linked 3D/2D/table, themes; 37 Playwright tests incl. axe light/dark/mobile | E-07, E-22 |
| OPS | OpenAPI + TS types drift check; backup/restore drill; Dockerfiles, Compose, CI workflow | E-23, E-24 |
| VALUE | Value ledger from simulated studies with evidence classes; research report; model/data cards | docs/research |

## Done in session 3 (verified; see EVIDENCE_INDEX E-28 … E-37)
| Task | Req IDs | Result |
|---|---|---|
| Full `docker compose up`; CI on GitHub | ARC-01, ARC-02, ARC-08 | stack runs and passes the reference journey; CI executes on GitHub (status in PROJECT_STATUS) |
| Load test on the reference data | ARC-07, BUS-015 | **met at 4 req/s, not at the declared 5 req/s, on 4 vCPU / 16 GiB**; five defects found and fixed |
| Web Vitals; WebGL-failure and network-interruption automation | UX-011, EXE-010, BUS-008, UX-012 | lab numbers published (mobile LCP above target); both failure paths automated |
| Lead-time-demand model | ML-005, ML-007 | replaces summed-q90; simulation-checked only |
| Cross-encoder reranker hook; R2 review sheet | ARC-04, ML-006 | hook wired and unit-tested, **unevaluated**; 50-question sheet ready, **not reviewed** |
| Web client on generated API types | ARC-02 | done; contract drift check passes in CI |
| OpenTelemetry; alert routing; tenant export and deletion | ARC, BUS-018, BUS-023 | done and tested |
| Lint, secret and dependency scans, security review in CI | ARC-08, BUS-021 | in CI; self-review published |
| Rollback, failed-migration, outage rehearsals; WAL archiving and PITR | BUS-020, ARC-06, BUS-014 | rehearsals pass; PITR drill passes locally and in CI |
| DEF-02 atomic idempotency; DEF-03 shared rate limits | — | fixed |
| 30+ golden boundary tests; run-version (EXE-006) tests | ARC-03, EXE-006 | 69 golden cases; 5 consistency tests |
| Repo tidy | — | `storage_test/` removed, `templates/` duplicate removed |

## Next (planned; needs a person or something not available to the build)
| Task | Req IDs | Needs |
|---|---|---|
| Re-run the load test on the declared 8 vCPU / 32 GiB profile | ARC-07 | that machine |
| Manual screen-reader pass | UX-010 | a person with NVDA/VoiceOver (`docs/acceptance/screen-reader-checklist.md`) |
| Review the 50-question R2 sample; freeze v2 | ARC-04 | a reviewer (`docs/acceptance/r2-human-review.md`) |
| Evaluate the cross-encoder; validate the lead-time-demand model on real windows | ARC-04, ML-005 | model weights; licensed retail history |
| Field Web Vitals; server-rendered first screen for mobile LCP | UX-011 | real sessions; a design decision |
| Tenant-wide search ceiling; admission control under overload; pagination of inventory/documents | F-05, load-test finding 5/6 | design decisions |
| Independent security test | BUS-021 | third party |

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
| DEF-02 | medium | Idempotency key check not atomic under concurrent identical requests | fixed (atomic claim; `tests/test_reliability.py`) |
| DEF-03 | low | Rate limits are per process | fixed (PostgreSQL token buckets, shared across processes) |
| DEF-04 | low | One ACORD test query excluded due to source quoting mismatch | open (documented) |
| DEF-05 | high | Inventory page never selected the 3D view on WebGL-capable browsers (introduced by the layout-shift work) | fixed; found by the resilience tests |
| DEF-06 | high | Retrieval slowed ten-fold on the 11th request of a process (generic plan) | fixed (D-033); found by the load test |
| DEF-07 | medium | Planner returned a misleading MODEL_INVALID for unit prices above ~5e7 minor units | fixed; found by a golden boundary case |
| DEF-08 | medium | Web image build failed behind a proxy CA; worker container reported unhealthy | fixed; found by running compose |
| DEF-09 | low | Scenario/plan limited to 200 SKUs per run (422) while the default is "all SKUs" | open (documented; full catalogue = 10 runs) |
| DEF-10 | medium | No back-pressure: past capacity requests queue and the service takes minutes to recover | open (load test finding 5) |
