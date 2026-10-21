# SupplyLens canonical data contract (target application schema)

The following definitions are **target schemas**, not proof the external source datasets contain these fields. Never fill missing real fields with guessed values without marking them synthetic.

| Entity | Minimum fields | Additional notes |
|---|---|---|
| Product | tenant_id, sku_id, description, unit_of_measure | SKU key scoped to tenant/source; distinguish product code from a global ID |
| Sales event | transaction_id, date_time, sku_id, quantity, unit_price, currency, source_id | Negative quantities/returns handled explicitly; invoice data is not unconstrained demand |
| Inventory snapshot | snapshot_time, warehouse_id, sku_id, on_hand, allocated, available | Must satisfy available = on_hand - allocated unless documented reservation semantics differ |
| Supplier | supplier_id, supplier_name, active_from | Do not connect World Bank suppliers to UCI products without actual relation records |
| Supplier product term | supplier_id, sku_id, unit_cost, currency, MOQ, pack_multiple, effective_from, effective_to | Contains source_document_id; use temporal validity; real data frequently unavailable |
| Purchase order | po_id, supplier_id, created_at, status | Lines have sku_id, quantity, price, warehouse and promised_date |
| Receipt | receipt_id, po_line_id, sku_id, actual_date, accepted_quantity | Real PO/delivery outcomes require customer ERP/WMS access |
| Contract version | document_id, source, version_id, effective_date, original_uri, content_hash | Preserve supersession and citation spans |
| Forecast | sku_id, location_id, origin_date, horizon, prediction, quantile, model_version | Know which features existed at the origin date |
| Agent run | tenant_id, run_id, tool calls, trace refs, proposed action, approver, verifier | Keep state, replays, cost and checked end state |

All transformed records must include `data_origin` (`real_public`, `synthetic`, or `customer_authorized`), `source_dataset_id`, extraction/transformation version, and appropriate permissions. Money is a decimal plus ISO currency, never a bare float with unknown currency. Dates must include time zones where time-of-day matters. For the initial research, store the raw source file and checksum, then build a typed silver layer, a feature-store gold layer, and a retriever corpus while keeping their splits isolated.
