# SupplyLens tasks

States: planned · active · implemented · verified · blocked. "Verified" means a command in
EVIDENCE_INDEX.md ran and passed locally. Severity applies to open defects only.

## DATA — qualification and pipelines
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| Download UCI Online Retail II with receipt + hash | DAT-001, BUS-001 | verified | data/download_receipts.jsonl, E-01 |
| Bronze (XLSX→parquet) / silver typed lines / returns / quarantine / gold daily | DAT-001/003, BUS-002 | verified | tests/test_uci_ingest.py, E-02 |
| Cross-sheet overlap handling (1–9 Dec 2010) | DAT-003, BUS-002 | verified | test_cross_sheet_overlap_is_counted_once, E-02 |
| Raw hash unchanged after ingest | EXE-002 | verified | E-01, E-02 |
| Capability matrix (missing stock/cost/lead time disclosed) | BUS-003, DAT-007 | implemented | GET /api/v1/overview; test_overview_and_capabilities |
| Admit CUAD/ACORD/World Bank/TED/InventoryBench from owner's download | DAT-002/005 | planned | — |
| Mapping/validation UI for user uploads (beyond UCI adapter) | UX-004 | planned | — |

## FCST — forecasting research
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| Seasonal naive with training-only intervals; leakage test | ML-002/003 | verified | tests/test_seasonal_naive.py, E-03 |
| Forecast service, runs, model registry | BUS-004 | verified | tests/test_forecast_service.py |
| Freeze cohort/splits; LightGBM quantile; quantile TCN (3 seeds) | ML-001/002/004 | planned (next) | — |
| Full metric suite + paired comparison + model card | ML-005/008, BUS-004 | planned | — |
| Lead-time demand uncertainty (block bootstrap) | ML-005 | planned | — |

## PLAN — optimisation
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| CP-SAT planner, validator, explained infeasibility | ARC-05 | verified | tests/test_planner_fixture.py, E-04 |
| Reference policy-change case + delayed-knowledge + conflict | EXE-003/004/005 | verified | E-04, E-06 |
| Scenario studio (demand ×, delay, budget, safety, coverage) | UX-007 | implemented | UI checked manually; no automated test yet |
| Lost-sales simulator for policy comparison | ML-007 | planned | — |

## KNOW — policy knowledge and retrieval
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| Versioned documents, chunks with offsets, known_at/valid_from/supersedes | DAT-007 | verified | tests/test_api.py::test_document_and_evidence_endpoints |
| Hybrid lexical + vector + RRF + rule reranker, temporal/ACL filters | ARC-04 (partial) | implemented | manual run; evidence test |
| Frozen 100-question retrieval eval, R1a/R1b/R2 ablations | ARC-04, ML-006 | planned | — |
| Prompt-injection containment | EXE-011 | verified | test_prompt_injection_in_document_cannot_change_scope_budget_or_destination |

## AGENT / ACT — investigation, approval, execution
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| Deterministic LangGraph investigator with checkpoints and resume | AGT (partial) | verified | tests/test_agent_graph.py, E-06 |
| Approval binding, SoD, stale approval, edit revalidation | BUS-005/006, EXE-008 | verified | tests/test_actions.py, E-05 |
| Idempotent dispatch, duplicate delivery, timeout-after-success reconciliation, fenced leases | BUS-007, EXE-007/009, AGT-02 (partial) | verified | tests/test_actions.py, E-05 |
| 50 frozen agent scenarios with repeated trials | AGT-01 | planned | — |
| Durable job queue with heartbeat | ARC-06 (partial) | implemented | worker; no lease-timing test yet |

## UX — interface
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| Light/Dark/System persisted | BUS-010, UX-002 | verified | e2e theme test, E-07 |
| Linked table / 2D floor plan / 3D selection | BUS-009, UX-005, EXE-006 (partial) | verified | e2e selection test, E-07 |
| Reference journey in browser (draft → approve → reconciled) | UX-012, EXE-007 | verified | e2e journey test, E-07 |
| axe serious/critical = 0 on 5 screens, desktop + mobile (light) | UX-010 (automated part) | verified | e2e layout tests, E-07 |
| Manual screen-reader + keyboard journeys; dark-mode axe in CI | UX-010 | planned | dark checked once manually via axe dump, no serious contrast issues |
| WebGL-failure path | EXE-010 | implemented | fallback code; not automated |

## ORG / SEC / OPS
| Task | Req IDs | State | Evidence |
|---|---|---|---|
| RLS forced, non-owner app role, cross-tenant denial tests | SEC-01 (partial: ~12 cases) | verified | tests/test_db_rls.py, test_api.py, E-08 |
| OIDC auth code + PKCE | — | blocked | no identity provider configured |
| OpenAPI→TS generated client in CI | ARC-02 | planned | hand-written client today |
| Docker Compose clean start | ARC-01, EXE-001 | planned | colima 2 GB may be insufficient |
| OpenTelemetry, backups/restore drill, rate limits | ARC-06/08 | planned | — |

## Known defects
| ID | Severity | Description | State |
|---|---|---|---|
| DEF-01 | low | React warns "synchronously unmount a root" from drei `Html` under StrictMode | open |
| DEF-02 | medium | Idempotency key check is not atomic under concurrent identical requests (state guards still prevent double approval) | open |
