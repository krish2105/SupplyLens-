# R2 retrieval questions: human review (ARC-04)

**Status: the review sheet is ready; no person has reviewed anything yet.** Nothing in this repository may be described
as "independently checked" until the sheet below is filled in by someone who did not write the generator.

## Why this is needed

The 118 R2 questions were generated from the same simulated supplier terms that produced the agreements. A pass proves the
temporal mechanism (cutoff, effective date, supersession), not that a buyer would phrase the question this way, nor that the
expected passage is the right answer. ARC-04 asks for a *frozen, independently checked* set.

## What to review

`evaluations/tasksets/r2_review_sample.csv`: 50 of the 118 questions, drawn reproducibly (seed in
`evaluations/r2_review_pack.py`): every question of the five rare case types in full (historical-before-known 8, known-not-in-
force 4, future-effective 4, amended-in-force 4, unknown-product 10) and 20 of the 88 "current" questions.

The sheet has the question, the case type, the two dates, the expected term/version/section, and empty reviewer columns.
To also show the expected passage text (needs the UCI workspace loaded):

```
uv run python evaluations/r2_review_pack.py --with-evidence
```

## How to judge each row (answer yes/no; add a note whenever the answer is "no")

| Column | Question to ask |
|---|---|
| `question_is_clear` | Would a buyer ask this, and is it unambiguous? |
| `expected_passage_is_correct` | Reading the expected version and section, does it answer the question **as of** the stated knowledge cutoff and effective date? For `unknown_product` rows the correct answer is that the system abstains, so "yes" means no passage should be expected. |
| `dates_make_sense` | Are the effective date and knowledge cutoff consistent with the case type (for example, "known not in force" means known by the cutoff but effective later)? |
| `better_passage_exists` | Is there another permitted passage that answers it better? |

## Acceptance rule (proposed; the owner should confirm)

* Review at least the 50 rows above, by one reviewer; a second reviewer on 10 rows to estimate agreement.
* The set is "independently checked" when `question_is_clear`, `expected_passage_is_correct` and `dates_make_sense` are all
  "yes" for at least 95 % of rows. Rows that fail are corrected or dropped *in a new frozen version of the task file*
  (`r2_supplier_terms_v2.jsonl`), and R2 is re-run on v2; v1 results stay as published.
* Record the reviewer, date and agreement in `docs/acceptance/acceptance_register.csv` (ARC-04) only after that.

## Cross-encoder condition (R1b)

A cross-encoder reranker is implemented (`services/api/src/supplylens/knowledge/rerank.py`, off by default). It has **not**
been evaluated: its weights come from a model hub the build environment cannot reach. To run the comparison on a machine
that can:

```
uv pip install sentence-transformers
export SUPPLYLENS_RERANKER_MODEL=BAAI/bge-reranker-base      # or a local directory
uv run python evaluations/retrieval_study.py R2
```

The study reports the rule-based and cross-encoder orderings side by side; adopt the cross-encoder only if it does not
increase wrong-version-at-top (it can only reorder what the filters admitted, and supersession stays a hard rule).
