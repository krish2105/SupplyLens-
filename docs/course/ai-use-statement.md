# AI-use statement — DRAFT for the owner's approval

> **Status: DRAFT (2026-11-10). Not approved.** The owner (Krishna Mathur) reviews, corrects and approves this text before
> it goes into any submitted document. Lines marked **[owner to confirm]** are not yet confirmed. Each team member adds
> the AI tools they used for their own parts. This statement is attached to the interim deck, the final deck and the
> report, and is never removed or softened (Phase 8 brief, academic integrity).

## Why this statement exists

The Phase 8 brief records that S P Jain's Academic Integrity Policy (version of 24 February 2026) treats generative-AI
use in assessed work as misconduct unless the assessment allows it and the use is acknowledged, requires students to
acknowledge AI tools in written assessments and to reference in APA style, and restricts submitting one piece of work
for more than one assignment. **[owner to confirm]** the wording against the policy itself and the lecturer's answer on
how AI use must be acknowledged in this unit (asked: not yet; open action 8A.1b).

## Two different kinds of AI in this project

1. **AI inside the product (the subject of the project).** SupplyLens uses machine-learning and language models as
   part of what it does: LightGBM and a quantile TCN for forecasting, XGBoost and Prophet in the W1 study, logistic
   regression and LightGBM in D1 and PM1, a small CNN in QC1, `bge-m3` embeddings for retrieval, and a local
   `qwen2.5:7b` model (Ollama) that may phrase cited answers when enabled locally (off in the public demo). These are
   described, evaluated and limited in `docs/research/results.md` and `docs/course/metrics.md`.
2. **AI used to produce the work (what this statement acknowledges).** Tools that helped write code, analyse results,
   write documents or make images.

## AI tools used to produce the work

| Tool | Used for | Parts | How a person checked the output |
|---|---|---|---|
| Claude Code (Anthropic), an AI coding assistant | Writing and changing code and tests; running checks; drafting documentation, including the Phase 8 course documents in `docs/course/` (this statement, coverage map, metrics generator, interim deck, demo script, marker guide) | Code, analysis support, writing | Every change ran the repository's checks (ruff, pytest, contract check, type checks, lint, unit tests, browser tests, CI); every number in course documents is generated from the study registry by `scripts/course_metrics.py` (not typed by hand); **[owner to confirm]** what the owner reviewed by hand and how |
| **[owner to confirm]** any AI assistant used in earlier phases (Phases 0–7) | **[owner to confirm]** | **[owner to confirm]** | **[owner to confirm]** |
| ChatGPT image generation (OpenAI) **[owner to confirm]** | The illustrations in `docs/course/images/` (deck title and outcome dividers, D01–D05) and the app empty-state illustrations A02, A13, A16, A17, A18, made from the briefs in `docs/design/image-prompts-phase8.md` | Images only (no charts, data, diagrams or screenshots are generated) | Checked against the acceptance list in `docs/design/image-prompts-phase8.md` (size, transparency, no text, numbers, logos or people); the findings of the automated checks are recorded in Phase 8 evidence; **[owner to confirm]** the owner's own review |
| **[Atharva Soundankar to add]** | | | |
| **[Yash Petkar to add]** | | | |

## What was not delegated to AI

**[owner to confirm and complete]** For example: the choice of problem and scope, the decisions recorded in
`DECISIONS.md`, the approval of every study's headline in `evaluations/study_registry.json`, and the presentation
itself.

## References (APA 7 style; versions and dates to be confirmed by the owner)

- Anthropic. (2026). *Claude Code* [AI coding assistant]. https://claude.com/claude-code **[owner to confirm version and access date]**
- OpenAI. (2026). *ChatGPT* [Large language model with image generation]. https://chatgpt.com **[owner to confirm]**

---

AI use: this file is the statement itself (draft awaiting the owner's approval).
