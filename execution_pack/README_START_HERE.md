# SupplyLens | E2E Starter Pack

A developer execution brief and setup scaffolding for an enterprise-oriented inventory and procurement AI product. This is a specification and project starter, **not a built or tested application**. No external raw datasets, credentials, model weights, or customer data are included. This updated pack includes a real-dataset acquisition catalog and a strictly FICTIONAL operational fixture dataset.

## NEW: real-dataset research and download tools (21 October 2026)

- **Read `data/README_DATASETS.md` first**. It explains what can be fetched automatically, which downloads require acceptance of terms, and why unrelated datasets cannot be silently joined.
- Use `python scripts/download_datasets.py --list` and then `python scripts/download_datasets.py --profile core --dry-run`.
- On a machine with internet access, run `python scripts/download_datasets.py --profile core` to acquire official public sources where legally and technically available. The script writes acquisition receipts and SHA-256 hashes. Several sources are manual or need authentication.
- Use `python scripts/verify_datasets.py` to inspect availability and validate **synthetic** test records. Successful offline verification DOES NOT mean the real datasets have downloaded.
- Paste the updated `05_SHORT_WORK_PROMPT_WITH_DATA.txt` into ChatGPT Work when starting with the researched datasets.
- M5 stays strictly academic/non-commercial and must never be bundled into a sellable demo. Other rights limitations are recorded by source.

## Start in a new project folder

1. Create an empty folder named `SupplyLens`, then extract this ZIP **into that folder**. The files should appear directly within `SupplyLens/` (avoid adding an extra nested directory).
2. Use `scripts/download_datasets.py` in a network-enabled environment or place authorised datasets in `data/raw/`, retaining original filenames and versions. Place supplier policies, manuals, or contract documents in `knowledge/raw/`. If these are absent, tell the coding agent to begin with explicitly labelled *synthetic* fixtures and show what data are missing.
3. Open the folder in a ChatGPT Work coding environment with the file, terminal, and development access needed for the task; attach `01_SUPPLYLENS_MASTER_PROMPT.txt` and `02_SUPPLYLENS_EXECUTION_SPECIFICATION.docx` if the workspace cannot read folder contents directly.
4. Paste the contents of `05_SHORT_WORK_PROMPT_WITH_DATA.txt` (or use `03_SHORT_LAUNCH_PROMPT.txt` for a data-independent start). Keep the folder connected for subsequent sessions.
5. In a later session, paste `04_RESUME_PROMPT.txt` to continue from documented progress.

## Important files

- `01_SUPPLYLENS_MASTER_PROMPT.txt`: comprehensive execution instructions for the engineering agent.
- `02_SUPPLYLENS_EXECUTION_SPECIFICATION.docx`: full product, technical, academic research, security, experience, and rollout specification.
- `03_SHORT_LAUNCH_PROMPT.txt`: the concise prompt to paste in ChatGPT Work.
- `04_RESUME_PROMPT.txt`: the concise prompt to continue a later session.
- `specifications/`: chapter-level text alternatives extracted from the DOCX, with no new requirements.
- `templates/acceptance_register.csv`: requirements checklist, 80 numbered acceptance criteria extracted from the specification. All start `not_run`.
- `templates/dataset_manifest.csv`, `templates/data_mapping.csv`, and `templates/experiment_log.csv`: working tracking templates, intentionally empty except for headers.
- `fixtures/policy_change_case.json`: a synthetic example for checking amendment-aware decisions, **not live commercial data**.
- `PROJECT_STATUS.md`, `TASKS.md`, `DECISIONS.md`, `EVIDENCE_INDEX.md`: starter continuity documents. Replace placeholders with observed work; never mark unfinished tasks complete.

## Academic and commercial scope

Train and evaluate your own LightGBM and temporal neural forecast models against a seasonal baseline on admitted data; compare retrieval and agent variants using controlled experiments; demonstrate an operational decision workflow; and quantify clearly labelled **measured versus simulated** business outcomes. Enterprise sale readiness must be earned with security, integration, real-user, support, and customer-specific validation—not assumed from this brief.

## Data safety and reproducibility

Do not commit actual data, private contracts, credentials, model checkpoints, or user records into a public repository. Dataset uploads need provenance, rights/licence review, schema checks, immutable raw storage, and a verified mapping step. The initial folder structure and supporting templates are not substitutes for data-quality tests or legal review.

## Implementation priority

Build one complete working flow first: validated data import -> baseline forecast -> policy evidence -> feasible replenishment -> draft action -> state verification. Next expand with trained model comparison, advanced retrieval, interactive dashboards/3D, stateful agents, enterprise controls, and evaluation. This prevents a visually polished interface from concealing missing business functionality.
