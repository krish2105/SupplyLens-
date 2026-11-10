# Responsible AI in SupplyLens — controls, risks and evidence (DRAFT)

**Draft for the team to review** (unit outcome C, "develop responsible AI-based solutions", and course outcome CLO4,
ethics and social responsibility). Each row names a risk, the control that answers it, where the control is in the code,
the test that fails if the control is removed, and the evidence. Numbers are not repeated here: they are in
[`metrics.md`](metrics.md). Nothing here is a lab or exercise answer.

## 1. Controls

| Risk | Control | Code | Test that fails without it | Evidence |
|---|---|---|---|---|
| One workspace sees or changes another's records | Row-level security on every tenant table, forced for the app role; the app role is not the owner | `services/api/migrations/`, `services/api/src/supplylens/db.py` | `tests/test_db_rls.py` (`test_tenant_rows_invisible_across_tenants`, `test_cannot_write_into_other_tenant`); RED1 case `cross-workspace-records` | RED1 in metrics.md |
| A purchase is placed without a person's approval | Deterministic planner proposes; an approver approves the exact payload; the preparer cannot approve their own action; a changed payload or term makes an approval stale | `services/api/src/supplylens/actions/` | `tests/test_actions.py` (`test_preparer_cannot_self_approve`, `test_stale_payload_hash_and_version_rejected`, `test_changed_terms_make_approval_stale`) | AGT: unapproved external writes in metrics.md |
| An agent acts outside its rights | The investigator and the n8n agent have planner rights only (D-099); external writes need an approved action | `services/api/src/supplylens/agent/`, `infra/n8n/` | `tests/test_agent_graph.py`; AGT oracle scenarios | AGT in metrics.md |
| A generated answer invents a figure or cites nothing | Cite-or-withhold: every sentence cites a passage and every figure must appear in a cited passage; otherwise the answer is withheld with its reason | `services/api/src/supplylens/knowledge/generate.py` (`check`) | `tests/test_generated_answers.py` (`test_an_answer_that_is_uncited_ungrounded_or_refused_is_withheld`) | G1 in metrics.md |
| A supplier document carries instructions aimed at the model (prompt injection) | Text addressed to a model is not shown to it; answers with links or addresses are withheld (added after RED1's first run) | `generate.py` (`screened`, `LINK`) | `tests/test_generated_answers.py` (`test_text_addressed_to_a_model_is_never_shown_to_it`, `test_an_answer_carrying_a_link_or_address_is_withheld`) | RED1 (current run and the superseded first run) |
| Generated text reaches the public | Generation is off on the public demo; the demo profile refuses to start with generation on (D-041) | `services/api/src/supplylens/config.py` (`generation_available`) | `tests/test_generated_answers.py` (`test_the_demo_profile_refuses_to_start_with_generation_on`) | hosted check P8-E12 |
| The status assistant is used to change or leak records | Read-only and deterministic: change requests are withheld, every sentence cites a record, reads run under the workspace's row-level security, rate-limited like the answer endpoint | `services/api/src/supplylens/assistant/`, `services/api/src/supplylens/api/routes_assistant.py` | `tests/test_assistant.py` | AS1 in metrics.md |
| A support hand-off sends data to an outside service by accident | Dry run by default and always on the public demo; a real HubSpot call needs an explicit flag and a token in the process environment; the token is never logged or returned; one attempt, no retry | `services/api/src/supplylens/assistant/handoff.py`, `infra/n8n/supplylens-support-handoff.json` (inactive) | `tests/test_assistant.py` | — |
| Extracted contract terms are trusted without a check | Rule-based fields are shown as a DRAFT with their character span and are never used for planning | `services/api/src/supplylens/knowledge/extract.py`, `apps/web/components/extracted-terms.tsx` | `tests/test_extraction.py`; `apps/web/e2e/extraction.spec.ts` | X1 in metrics.md |
| Simulated numbers are read as real | Every number carries its kind (observed, forecast, assumed, simulated, synthetic, derived); capability rows show their basis | `apps/web/components/ui.tsx` (`Provenance`, `CapabilityStatus`) | `apps/web/components/ui.test.tsx`; `apps/web/e2e/theme.spec.ts` (F2) | P8-E04 |
| An allocation under a tight budget treats groups unequally | Reweighing study with the cost of closing the gap reported | `evaluations/fairness_study.py` | `tests/test_fair_allocation.py` | FA1 in metrics.md |
| A classifier misses failures unevenly across groups | Re-weighting, SMOTE, threshold moving and adversarial debiasing compared with recall and false-alarm gaps per group | `evaluations/imbalance_study.py`, `evaluations/adversarial_child.py` | `tests/test_imbalance_study.py` (SMOTE touches training rows only; gaps and cost computed correctly) | B1 in metrics.md |
| Results are overstated | Negative results kept in the registry and on the Research page; superseded runs named with the reason; exploratory runs quoted only with that word (D-109) | `evaluations/study_registry.json`, `scripts/course_metrics.py` | `tests/test_course_metrics.py` | metrics.md |
| AI use in the course work is hidden | AI-use statement in every course document | [`ai-use-statement.md`](ai-use-statement.md) and the closing line of each course document | none: checked by review | — |

## 2. What is not controlled yet

- Human-written questions for the answer layer (G2) are not written: they must come from people, not from a model.
- The red team is 17 hand-written attacks with pattern rules and one local model: a screen, not a proof.
- Real logistics, telematics and delivery data are not used (no owner approval); FE1, ET1 and RT1 are method checks.
- Model monitoring covers the served forecaster only; the study models are not served.

## 3. Questions for the team

- Who reviews a new study's headline before it is registered (today: the person who ran it)?
- What would make the team switch generation on for a real user, and who signs that off?

---

AI use: see [`ai-use-statement.md`](ai-use-statement.md) (draft awaiting the owner's approval).
