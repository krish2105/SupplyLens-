# Prompt to start the next working session: Phase 8, Session 8B

Session 8A is complete (2026-11-10, `phases/PHASE-08.md`). The next session is **8B**, after Week 6. The full brief is
`docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md` (paste its common header, then the 8B block); the per-session prompt
below is the short form from `PHASE-08_SHORT_PROMPTS.md`, adjusted to v4 (no v5 brief exists: D-100).

**Update 2026-11-10:** most of 8B was done early at the owner's request (`phases/PHASE-08.md`, "Course-coverage build"):
WP3 (ET1, RT1 on generated data), WP4 (W2), WP5 (B1), WP6 (AS1, dry-run HubSpot hand-off), WP7 (X1, Extracted terms; no
PDF intake, no confirm step), WP8 (RED1) and A17/A18. What 8B still holds: KNOW-P7-01 for the evidence answer, G2
(human-written questions, written by people), PDF intake and the confirm step (migration 0012, owner decision on the
hosted database), real logistics data (owner approval), and a real HubSpot test account if the owner wants one. Then 8C.

Before starting: fill `private/owner-answers-8B.md` (never committed).

```text
You are starting with zero context. The repository in this folder (SupplyLens, github.com/krish2105/SupplyLens-) is the only source of truth.

Read these fully before doing anything:
- @docs/agent-handoff/PHASE-08_COURSE_PROMPT_v4.md  (the brief: common header, then the 8B block)
- @docs/agent-handoff/phases/PHASE-08.md  (what 8A did; trust it only after checking git log and CI)
- @private/owner-answers-8A.md and @private/owner-answers-8B.md  (my answers; ask only what is missing or unclear)
- @private/unit-outline.docx  (never commit anything from private/)
- @docs/design/image-prompts-phase8.md  (for WP-ART; you never generate images)

Do ONLY "Session 8B": follow the "Common header", then the 8B block, in this order:
1. Restore context. No code changes yet. Re-check the licence of every dataset I approved on its official page before downloading; download nothing I did not approve.
2. Ask me in ONE message only what my answers file does not settle (placement of new UI included, per WP-UI), then wait.
3. Work in this order: WP4 (LSTM), WP5 (imbalance and parity), WP3 (logistics), WP7 (PDF intake and extraction, X1 on CUAD), WP6 (status assistant and hand-off), WP8 (KNOW-P7-01, red team, G2), then WP-ART for A17/A18 once their screens exist. Follow WP-UI for every screen you add or change.
4. Each study: registry entry, metrics files, Research card, a test that can fail, honest headline (negative results kept). Regenerate docs/course/metrics.md. Run all checks before any push. Never put secrets in files or chat.
5. Finish with a short summary, the new study headlines, and my open actions, then STOP. Do not start 8C.

Rules: never do my individual work (no lab reports, exercise or quiz answers). Never invent numbers, team members, references or results. Never weaken security, approvals or the demo lockdown. Never generate images. Never push to main in the 48 hours before a presentation. Commits carry no AI mention (D-101); course documents carry the AI-use statement. If the brief conflicts with the repository, tell me and ask before acting.
```

Known before 8B starts: the id "L1" is taken by the lead-time demand study (STUDY-P8-01); Playwright's Firefox does not
start on the owner's Mac, so run that project with `scripts/e2e_firefox_docker.sh` (ENV-P8-01); A17 and A18 are
prepared and rendered nowhere until WP7 and WP6 build their screens; IB scored only the 600 real-trajectory
instances (IB-P8-01); exploratory runs may be quoted only with their label (D-109); the outline check is
`docs/course/outline-check.md`.
