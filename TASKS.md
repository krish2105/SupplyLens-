# SupplyLens tasks

- [ ] Inspect selected workspace, toolchain, user datasets and document sources.
- [ ] Complete data rights and provenance manifests.
- [ ] Build a vertical slice: data import -> baseline forecast -> policy evidence -> feasible replenishment -> draft action -> verify saved state.
- [ ] Train, compare, and evaluate LightGBM and quantile TCN models.
- [ ] Implement and evaluate advanced RAG.
- [ ] Implement durable agent tools, approvals, execution and reconciliation.
- [ ] Connect interactive UI, themes, 2D views, charts and schematic/real 3D based on available layout data.
- [ ] Validate tenancy, accessibility, performance, recovery, and security controls.
- [ ] Reproduce dissertation results and define enterprise pilot requirements.

For full traceability, maintain `templates/acceptance_register.csv` by ID and link each tested result in `EVIDENCE_INDEX.md`.

## Public dataset acquisition tasks (new)

- [ ] In a network-enabled Work session, inspect `data/README_DATASETS.md` and `data/DATASET_CATALOG.csv`.
- [ ] Download core real sources using `scripts/download_datasets.py`; confirm publisher archives are complete and hashes are recorded.
- [ ] Manually review and accept ContractNLI terms, if its verification task is included.
- [ ] Obtain M5 using authenticated Kaggle CLI solely for the academic experiment, after accepting its rules.
- [ ] Run `scripts/verify_datasets.py --require-core` and resolve each missing source.
- [ ] Build bronze/silver/gold ingestion with provenance and no invented cross-dataset keys.
- [ ] Keep demo's fictional supplier terms and any generated inventory/PO events visibly marked synthetic.
- [ ] Confirm third-party content rights before commercial redistribution or model shipment.
