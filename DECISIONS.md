# SupplyLens decision log

| ID | Date | Decision | Reason | Alternatives | Status |
|---|---|---|---|---|---|
| D-001 | 2026-10-21 | Treat the specification stack as proposed defaults | From the pack | — | Superseded by D-002+ |
| D-002 | 2026-10-21 | Repository at `SupplyLens/` root; original packs and ZIPs left untouched and git-ignored | Owner choice | Build inside pack folder | Accepted (owner) |
| D-003 | 2026-10-21 | UCI Online Retail II is the only public dataset admitted in phase 1; M5 skipped | Owner choice; M5 is non-commercial and needs owner rule acceptance | Full core profile | Accepted (owner) |
| D-004 | 2026-10-21 | No generative LLM; extractive answers and deterministic agent nodes | Owner choice | Ollama qwen2.5, Claude API | Accepted (owner) |
| D-005 | 2026-10-21 | Local bge-m3 (Ollama, 1024-d) for embeddings, lexical fallback | Owner choice; keeps data local | No neural models | Accepted (owner) |
| D-006 | 2026-10-21 | Bold visual direction on the spec palette; signature = dual-clock rail | Owner chose "bold"; the two clocks are the product's differentiator | Minimal enterprise | Accepted (owner) |
| D-007 | 2026-10-21 | Native dev runtime (Homebrew PG17 + pgvector), compose later | colima VM has 2 CPU/2 GB | Docker-first | Accepted |
| D-008 | 2026-10-21 | One `supplylens` Python package shared by API and worker; ML/opt as sibling packages | Spec: shared domain services, separate processes | Microservices | Accepted |
| D-009 | 2026-10-21 | Memberships, tenants, users are control-plane tables without RLS, read-only to the app role | Sign-in must list a user's tenants before tenant context exists | RLS + SECURITY DEFINER lookup | Accepted |
| D-010 | 2026-10-21 | Quarantine exact duplicate sale lines (keep first) and cross-sheet overlap rows | Publisher sheets overlap 1–9 Dec 2010; duplicates inflate the target | Keep all rows | Accepted |
| D-011 | 2026-10-21 | Non-merchandise codes (POST, D, M, fees…) quarantined via code pattern `^\d{5}[A-Za-z]{0,3}$` | Not products; documented in report | Hand list | Accepted |
| D-012 | 2026-10-21 | Workspace as-of = 2011-12-08 23:59 UTC (9 Dec is partial) | Avoid partial-day origin | 9 Dec | Accepted |
| D-013 | 2026-10-21 | UCI operational layer is simulated from assumption set `uci-sim-ops v1` (seed 20111208): purchase cost = 45–65% of median selling price, 4 fictional suppliers, generated agreements labelled SIMULATED, two amendments | Source has sales only (BUS-003, ML-007) | Leave planning unavailable | Accepted |
| D-014 | 2026-10-21 | Reference case added to Demo workspace as fictional documents (spec chapter 4 values) | Make EXE-003 visible in the UI | Tests only | Accepted |
| D-015 | 2026-10-21 | Replenishment need = q50 path + assumed safety days; q90 sum shown only as uncalibrated reference | Spec: summing daily quantiles is not a calibrated lead-time quantile | Sum q90 | Accepted |
| D-016 | 2026-10-21 | Planner allows explicit shortfall with an assumed penalty in investigations; reference case runs with shortfall disallowed | Budget-constrained portfolios are otherwise always infeasible | Hard coverage only | Accepted |
| D-017 | 2026-10-21 | Dev sign-in via signed HttpOnly cookie, CSRF header, same-origin proxy through Next | OIDC not configured; spec forbids home-grown passwords (none used) | — | Accepted (dev only) |
| D-018 | 2026-10-21 | GET endpoints accept `?ws=` for the workspace (EventSource cannot set headers); mutations still require the header | SSE requirement | Polling | Accepted |
| D-019 | 2026-10-21 | Web dev server on port 3100 | Port 3000 used by another local project | — | Accepted |
| D-020 | 2026-10-21 | Light-theme accent darkened to #0F6B55 and risk to #8A5208 | axe measured 4.39:1 and 4.01:1 on soft chips | Larger text | Accepted |

## Authorisation scope recorded
Routine local development, local databases, dataset download of UCI (owner-approved). No deployments,
spending, external writes or credentials were used. The sandbox ERP is local only.
