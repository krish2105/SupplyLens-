# Claude Code short prompts for Phase 8 (paste one per session)

Start a NEW Claude Code session in the repository folder for each one (`cd SupplyLens- && git pull && claude`).

## Files that must be in the repository first

| File | Path in the repo | Commit? |
|---|---|---|
| Phase 8 brief | `docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md` | yes |
| Image prompts | `docs/design/image-prompts-phase8.md` | yes |
| Hosted defect screenshot | `docs/screenshots/phase8/owner-2026-11-10-overview-light.png` | yes |
| Unit outline | `private/unit-outline.docx` | NO |
| Answers 8A / 8B / 8C | `private/owner-answers-8A.md`, `-8B.md`, `-8C.md` | NO |

Before anything else, add this line to `.gitignore` and commit it:

```text
private/
```

---

## Session 8A — now, before Week 6

```text
You are starting with zero context. The repository in this folder (SupplyLens, github.com/krish2105/SupplyLens-) is the only source of truth.

Read these fully before doing anything:
- @docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md  (the brief)
- @private/owner-answers-8A.md  (my answers; ask me only what is missing or unclear)
- @private/unit-outline.docx  (course outline and rubrics; never commit anything from private/)
- @docs/screenshots/phase8/owner-2026-11-10-overview-light.png  (hosted demo defect for WP0)
- @docs/design/image-prompts-phase8.md  (illustration briefs; you never generate images)

Do ONLY "Session 8A": follow the "Common header", then the 8A block, in this order:
1. Restore context (8A.0). No code changes yet. Confirm private/ is in .gitignore.
2. Ask me in ONE message only the 8A.1 questions my answers file does not settle, then wait.
3. WP0 first (hosted UI fixes F1–F5, each with a test that fails before the fix), then 8A.2, WP1, WP2, WP9a.
4. Run all checks before any push. Record evidence and decisions as the brief says.
5. Finish with a short summary and my open actions, then STOP. Do not start 8B.

Rules: never invent numbers, team members, references or results. Never weaken security, approvals or the demo lockdown. Never push to main in the 48 hours before a presentation. If the brief conflicts with the repository, tell me and ask before acting.
```

---

## Session 8B — after Week 6, finish before the Week 10 lab

```text
You are starting with zero context. The repository in this folder (SupplyLens, github.com/krish2105/SupplyLens-) is the only source of truth.

Read these fully before doing anything:
- @docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md  (the brief)
- @docs/agent-handoff/phases/PHASE-08.md  (what 8A did; trust it only after checking git log and CI)
- @private/owner-answers-8A.md and @private/owner-answers-8B.md  (my answers; ask only what is missing or unclear)
- @private/unit-outline.docx  (never commit anything from private/)
- @docs/design/image-prompts-phase8.md  (for WP-ART; you never generate images)

Do ONLY "Session 8B": follow the "Common header", then the 8B block, in this order:
1. Restore context. No code changes yet. Re-check the licence of every dataset I approved on its official page before downloading; download nothing I did not approve.
2. Ask me in ONE message only what my answers file does not settle (placement of new UI included, per WP-UI), then wait.
3. Work in this order: WP4 (LSTM), WP5 (imbalance and parity), WP3 (logistics), WP7 (PDF intake and extraction, X1 on CUAD), WP6 (status assistant and hand-off), WP8 (KNOW-P7-01, red team, G2), then WP-ART if I approved images. Follow WP-UI for every screen you add or change.
4. Each study: registry entry, metrics files, Research card, a test that can fail, honest headline (negative results kept). Run all checks before any push. Never put secrets in files or chat; the HubSpot key, if any, is only in my .env.
5. Finish with a short summary, the new study headlines, and my open actions, then STOP. Do not start 8C.

Rules: never invent numbers, team members, references or results. Never weaken security, approvals or the demo lockdown. Never push to main in the 48 hours before a presentation. If the brief conflicts with the repository, tell me and ask before acting.
```

---

## Session 8C — Weeks 10 to 12, finish before the final presentation

```text
You are starting with zero context. The repository in this folder (SupplyLens, github.com/krish2105/SupplyLens-) is the only source of truth.

Read these fully before doing anything:
- @docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md  (the brief)
- @docs/agent-handoff/phases/PHASE-08.md  (what 8A and 8B did; check git log and CI)
- @private/owner-answers-8A.md, @private/owner-answers-8B.md and @private/owner-answers-8C.md  (my answers)
- @private/unit-outline.docx  (rubrics 3.2 and 3.4; never commit anything from private/)
- @docs/course/metrics.md and @docs/course/coverage.md

Do ONLY "Session 8C": follow the "Common header", then the 8C block, in this order:
1. Restore context. No code changes yet. Regenerate docs/course/metrics.md and confirm it matches the registry.
2. Ask me in ONE message only what my answers file does not settle, then wait.
3. WP9 (responsible AI, model and data cards), WP10 (business case with labelled assumptions and a sensitivity table), WP11 (final deck, 10-minute demo script, report, rubric map, case links, Q&A prep, contributions). Verify every reference by opening it or finding it in a catalogue; drop any you cannot verify. Every number must come from metrics.md.
4. Walk the 10-minute script once on the hosted demo and once on the local profile; record timing. Export the report and deck in the formats in my answers. Tag course-final only after I confirm.
5. Write NEXT_SESSION_PROMPT.md for Phase 9, finish with a short summary and my open actions, then STOP.

Rules: never invent numbers, team members, references or results. Never weaken security, approvals or the demo lockdown. Never push to main in the 48 hours before a presentation. If the brief conflicts with the repository, tell me and ask before acting.
```
