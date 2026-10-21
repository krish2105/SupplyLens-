# SupplyLens datasets: acquisition and verified research plan

**Current ZIP status (21 October 2026): no external raw datasets are bundled.** The ZIP includes the original project pack, 13 researched source entries, verified links, a network-ready acquisition program and a reproducible **fictional** demo dataset. The generator output is clearly synthetic. This environment could not connect to the publishers to download the real files.

## Download real sources in a network-enabled Work terminal or on your own machine

Open a terminal at the project root, with Python 3.10+ and Git installed. No Python third-party packages are needed for the downloader's UCI, World Bank, TED or Figshare operations. Git downloads require Git; M5 requires the Kaggle CLI and authentication.

```bash
python scripts/download_datasets.py --list
python scripts/download_datasets.py --profile core --dry-run
python scripts/download_datasets.py --dataset online_retail_ii acord inventory_bench
python scripts/download_datasets.py --dataset cuad world_bank_ipf_awards ted_notices
python scripts/verify_datasets.py
```

If TED query syntax has changed, check the official TED v3 Swagger documentation and provide a bounded `--ted-query`. The downloader defaults to three pages of search results, not the entire EU corpus. Example:

```bash
python scripts/download_datasets.py --dataset ted_notices --ted-query 'FT~"industrial pumps" AND PD>=20240101 SORT BY publication-date DESC' --ted-pages 5
```

World Bank's public API can expose hundreds of thousands of records. If you only need a small initial sample, explicitly request a partial result and treat the result as INCOMPLETE:

```bash
python scripts/download_datasets.py --dataset world_bank_ipf_awards --max-worldbank-pages 5
```

This writes `awards.partial.jsonl` rather than masquerading as a complete export. Use `--max-worldbank-pages 0` for the full public export (default), and inspect `acquisition_metadata.json`.

## Academic-only M5

M5's competition rules limit use to competition, academic and non-commercial purposes. Visit the official rules page, accept the rules with your own Kaggle account, install/authenticate the `kaggle` CLI, then run:

```bash
python scripts/download_datasets.py --dataset m5 --ack-m5-noncommercial
```

Raw M5 content belongs ONLY in `data/raw/academic/m5/`. Do not redistribute it as part of a commercial SaaS demo, sell a product preloaded with it, or assume commercial rights in weights trained on it.

## Manual and conditional sources

- **ContractNLI:** Go to https://stanfordnlp.github.io/contract-nli/, read and accept the terms yourself, use its Download Dataset control, and place the resulting JSON/archive in `data/raw/core/contract_nli/`. Do not bypass the terms with a hardcoded raw link.
- **NASA C-MAPSS:** Visit https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data; select the official ZIP resource and download to `data/raw/optional/nasa_cmapss/`. NASA's dataset page does not specify a licence, so do not redistribute in a commercial installation without a rights assessment.
- **Building Data Genome 2:** Optional, uses an Attribution-ShareAlike dataset licence. After reviewing obligations, use `--dataset bdg2 --ack-sharealike`.
- **OULAD:** Optional education data; `--dataset oulad` uses Figshare's article API and downloads the publisher-listed files.
- **Poly Haven:** Manually select individual CC0 3D assets at https://polyhaven.com/ . Assets are not an enterprise warehouse-layout dataset. Procedural racks, pallets and bins are recommended.

## Download everything currently automatable

```bash
python scripts/download_datasets.py --profile all --ack-m5-noncommercial --ack-sharealike
```

**Only run the all-sources command if you genuinely want the optional datasets and have accepted the relevant licences.** Manual-rights sources will still require you to visit the publisher. It may consume multiple gigabytes once clones, extracted data and indexes are included. Save source references and acquisition receipts (`data/download_receipts.jsonl`). A completed script does not mean every manual source is present.

## What is included immediately

- `data/synthetic/operations/`: six fictional suppliers, 36 fictional products, 37 synthetic supplier terms, 36 synthetic inventory snapshots, 18 fictional draft purchase orders, and a date-effective policy truth fixture.
- `knowledge/synthetic_contracts/`: three fictional documents to test retrieval and amendment handling.
- `scripts/generate_synthetic_ops.py`: regenerates the synthetic fixtures deterministically; never presents them as observations about real firms.
- `data/source_manifest.json` / `data/DATASET_CATALOG.csv`: 13 sources with data origin, licence, purpose, acquisition path, and non-download status.
- `scripts/verify_datasets.py`: checks optional real dataset availability and synthetic invariants.

## Never silently join unrelated public datasets

UCI Online Retail II's StockCode does NOT identify a World Bank supplier, TED notice, ACORD contract, CUAD clause, or InventoryBench article. The source datasets describe different businesses and domains. Use each for its own experiment or isolated product module. For operational end-to-end demo testing, use an explicitly synthetic supplier-SKU map; identify it as fabricated, keep it out of the real data, and never attach synthetic negative performance claims to named real suppliers.

Sales transactions are not direct measurements of unconstrained demand. Supplier lead time, MOQ, stockouts, stock-on-hand, promised/actual receipts and contractual amendments remain unavailable in one reliable public joined dataset. These must be simulated or supplied by an authorised customer.

## Provenance and data storage

Keep original downloads immutable under `data/raw/`, record exact source URLs and hashes, and use separate `data/silver/` and `data/gold/` for transformations. Do not check raw data, secrets, customer information or model weights into a public Git repository. Review all licence conditions before redistributing anything to customers. This starter pack provides source facts and tools, not legal clearance.
