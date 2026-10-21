# SupplyLens external dataset research | 21 October 2026

The following are official/publisher sources from the completed public-data research. Their entries in `data/source_manifest.json` define an executable acquisition plan; availability may change after this document's date. No external downloads are included in this pack.

| Source | Origin | Fit | Rights overview | Official primary URL |
|---|---|---|---|---|
| UCI Online Retail II | Real online sales transactions, 2009-2011 | SKU forecasting and returns; 1,067,371 transaction rows | CC BY 4.0 attribution | https://archive.ics.uci.edu/dataset/502/online+retail+ii |
| M5 | Real retail histories presented as competition data | Academic hierarchical forecasting, calendar, selling prices | Competition academic/non-commercial limitation; research only | https://www.kaggle.com/competitions/m5-forecasting-accuracy/rules |
| CUAD | Real commercial contracts, expert-labelled | Clause extraction and evidence-linked contract RAG | CC BY 4.0 data with attribution; inspect original rights | https://www.atticusprojectai.org/cuad/ |
| ACORD | Real contract clauses, expert relevance labels | Train and evaluate rerankers with supplied query splits | CC BY 4.0 dataset | https://www.atticusprojectai.org/acord/ |
| ContractNLI | Real NDAs with entailment/evidence labels | Citation verification | CC BY 4.0 plus publisher download terms | https://stanfordnlp.github.io/contract-nli/ |
| World Bank IPF awards | Public structured procurement awards | Public supplier/award analytics | CC BY 4.0 with attribution | https://financesone.worldbank.org/contract-awards-in-investment-project-financing-since-fy-2020/DS00005 |
| EU TED | Authentic published procurement notices | Tender search, document RAG, public procurement monitoring | Generally commercial reuse, inspect third-party rights | https://docs.ted.europa.eu/api/latest/search.html |
| InventoryBench | Mixed synthetic and real-derived inventory scenarios | Agent decision and optimisation benchmark | MIT repo code; check H&M underlying rights | https://github.com/TianyiPeng/InventoryBench |
| UCI AI4I | Explicitly synthetic maintenance dataset | Small optional classification extension | CC BY 4.0 | https://archive.ics.uci.edu/dataset/601/ai4i2020 |
| NASA C-MAPSS | Simulated engine time series | Optional DL remaining useful life study | Licence not specified on dataset page | https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data |
| Building Data Genome 2 | Real building energy measurements, 2016-2017 | Optional energy forecasts | Attribution-ShareAlike, check exact version | https://github.com/buds-lab/building-data-genome-project-2 |
| OULAD | Real anonymised education data | Optional learning analytics, not core | CC BY 4.0 attribution | https://research.stem.open.ac.uk/ouanalyse/dataset/ |
| Poly Haven assets | CC0 3D HDRI, textures, and models | Optional UI scene assets, not warehouse telemetry | CC0 on individual assets; respect site rights | https://polyhaven.com/license |

## Recommended procurement analytics and forecasting split

The coherent core is **UCI Online Retail II** for the commercial-style sales story; **World Bank IPF awards + TED** for separate public procurement intelligence; **CUAD + ACORD + ContractNLI** for independently evaluated contract retrieval/extraction/verification; **InventoryBench** for inventory agent baselines; and **synthetic operational state** strictly marked synthetic for connected order-to-delivery demonstration.

Keep **M5** in a separate academic benchmark profile. InventoryBench's per-case historical context is very short, so it is not the primary source for training a substantial DL forecaster. Optional AI4I, NASA and energy/LMS data are extensions, not required for the supply-and-procurement thesis.

## Research controls

- **Time-aware forecasting:** rolling-origin splits, appropriate calendars, avoid future promotions/labels in features. Sales are not equivalent to unconstrained demand.
- **Document RAG:** preserve original document source, contract-level isolation and ACORD's own query split; validate CUAD/ACORD provenance overlap before claiming an independent test.
- **Supplier terms:** do not present CUAD contracts, TED tenders, or World Bank award descriptions as directly joined ERP supplier terms for UCI StockCodes.
- **Agents:** evaluate final simulated inventory and draft PO state, correctness of evidence, version-selected policies, constraints, duplicate-action recovery and latency; not just narrative answers.
- **Licensing:** do not give blanket commercial permission to datasets, derived models, or source documents without confirming the relevant licences and any third-party content.

## Trust boundaries

Real raw datasets are immutable `data/raw`; fictional data have `data_origin=synthetic` and live only in `data/synthetic` and `knowledge/synthetic_contracts`. No source provides verified private supplier lead times, customer-specific stock records, or reliable enterprise ROI. Build the product with replaceable ERP/WMS ingestion connectors so an MNC pilot can use authorised customer exports rather than pretending the public sources are from the same firm.
