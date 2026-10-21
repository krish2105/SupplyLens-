# SupplyLens End to End Execution Specification

> Product engineering research and enterprise delivery

Version 1.0  |  20 October 2026

Build an evidence-grounded inventory and procurement application that combines trained forecasting models, advanced retrieval, stateful agent execution and an interactive planning workspace. This document defines the implementation scope and the evidence required to move from a controlled product to an enterprise pilot and a qualified production release.

The intended reader is the engineering agent or team implementing SupplyLens for a master's project in AI in Business. The application must support rigorous model comparisons and an honest business case while delivering a complete, usable workflow for inventory planners and buyers.

| Gate | Purpose | Evidence required |
| --- | --- | --- |
| P0 | Complete controlled product | Integrated data to forecast to plan to evidence to verified sandbox action |
| P1 | Enterprise pilot | Qualified data and identity, tested sandbox connector, recovery and user evaluation |
| P2 | Qualified production | Contracted capability, operational ownership, security and recovery evidence, customer acceptance |

Use 01_SUPPLYLENS_MASTER_PROMPT.txt as the execution instruction and 03_SHORT_LAUNCH_PROMPT.txt as the starting message. The plain-text chapters and templates in the bundle support selective reading and reproducible handoffs.

Status of this pack: implementation specification. Performance numbers are proposed targets. Acceptance results begin as not run. No application, customer integration or commercial result is asserted by this document.

# Reading guide

Read the entire brief before fixing the implementation plan. During development, keep the relevant chapter open and map work to its requirement IDs. Use the acceptance register to record observed evidence, not intended behaviour.

1 Product and commercial requirements. Buyer, workflow, features, release gates, integrations, support and business value.

2 Architecture and agent execution. Data, APIs, forecasting, optimisation, retrieval, agents, durable execution and identity.

3 Data research and interactive experience. Real-data admission, model training, evaluation, themes, 3D and linked charts.

4 Execution and acceptance. Repository responsibilities, reference scenario, continuity and application handover.

Requirement prefixes: BUS covers product and commercial evidence; ARC covers architecture; SEC covers security; AGT covers agent execution; DAT covers data; ML covers research; UX covers interaction; EXE covers end-to-end delivery. The JSON register carries all identifiers and blank result fields.

The user supplies the project folder and datasets. Where operational fields are absent, preserve that fact and use a separate labelled simulation only for the tasks it can support. The product should remain useful during model-provider or connector outages through deterministic tools and previously verified data.

## Short launch prompt

Build SupplyLens end to end in the selected project folder. Read 01_SUPPLYLENS_MASTER_PROMPT.txt and 02_SUPPLYLENS_EXECUTION_SPECIFICATION.docx completely, then use them as the implementation brief, subject to my instructions and the environment's permissions.

Inspect the workspace and my datasets, preserve raw files, record assumptions, and begin implementation immediately after a concise plan. Deliver the trained ML/DL pipeline, advanced RAG, stateful agent, inventory optimiser, working backend, and fully interactive modern UI with Light/Dark/System themes, linked 3D warehouse visuals, charts, scenarios, and evidence panels.

Work through the defined gates, test each complete workflow, and maintain PROJECT_STATUS.md, TASKS.md, and evidence of actual results. Continue routine local work without repeated confirmation. Prepare external deployments and integrations for review; obtain any missing authorization before live writes or spending. Clearly label simulated data and unverified capabilities. If execution limits interrupt the work, save an exact checkpoint and resume instructions.
