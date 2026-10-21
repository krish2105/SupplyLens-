"""Ingest UCI Online Retail II into a tenant: datasets, silver lines, returns, quarantine,
products and the gold daily table. Idempotent by file hash; never modifies the raw file."""
from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from supplylens_ml import uci

from ..config import REPO_ROOT
from ..db import tenant_session

SOURCE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"


def _copy_frame(session, temp_table: str, ddl: str, frame: pd.DataFrame) -> None:
    """Bulk-load into a session temp table (COPY FROM is unavailable on RLS tables)."""
    session.execute(text(f"CREATE TEMP TABLE {temp_table} ({ddl}) ON COMMIT DROP"))
    buf = io.StringIO()
    frame.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    raw = session.connection().connection.driver_connection
    with raw.cursor().copy(f"COPY {temp_table} FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)


def ingest(tenant_id: uuid.UUID, zip_path: Path, bronze_root: Path | None = None) -> dict:
    zip_path = Path(zip_path)
    digest = uci.sha256_file(zip_path)
    with tenant_session(tenant_id) as s:
        existing = s.execute(
            text("SELECT id, report FROM datasets WHERE sha256 = :h"), {"h": digest}
        ).first()
        if existing:
            return {"dataset_id": str(existing.id), "reused": True, "report": existing.report}

    bronze = uci.read_bronze(zip_path, bronze_root or REPO_ROOT / "data" / "bronze" / "online_retail_ii")
    classified = uci.resolve_sheet_overlap(
        {sheet: uci.classify(sheet, df) for sheet, df in bronze.items()})
    report = uci.qualification_report(zip_path, classified)
    dataset_id = uuid.uuid4()
    acc = pd.concat([c.accepted for c in classified.values()], ignore_index=True)
    ret = pd.concat([c.returned for c in classified.values()], ignore_index=True)
    qua = pd.concat([c.quarantined for c in classified.values()], ignore_index=True)
    daily = uci.daily_units(acc)
    descr = (acc.groupby("sku_id")["description"].agg(lambda d: d.value_counts().index[0])
             .rename("description"))
    span = acc.assign(day=acc["ts"].dt.date).groupby("sku_id")["day"].agg(["min", "max"])
    products = span.join(descr).reset_index()

    line_cols = ["sheet", "source_row", "invoice", "sku_id", "qty", "price_minor", "ts",
                 "customer_id", "country"]
    line_ddl = ("sheet text, source_row int, invoice text, sku_id text, qty int, price_minor bigint, "
                "ts timestamp, customer_id text, country text")
    with tenant_session(tenant_id) as s:
        s.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, name, source_kind, license, source_url, file_name, "
                "sha256, bytes, schema_version, status, report) VALUES (:id, :t, 'UCI Online Retail II', "
                "'public', 'CC BY 4.0', :u, :f, :h, :b, :v, 'READY', CAST(:r AS jsonb))"
            ),
            {"id": dataset_id, "t": tenant_id, "u": SOURCE_URL, "f": zip_path.name, "h": digest,
             "b": zip_path.stat().st_size, "v": uci.TRANSFORM_VERSION, "r": json.dumps(report)},
        )
        s.execute(
            text(
                "INSERT INTO locations VALUES (:t, :l, 'UCI online retailer (single fulfilment point)', "
                "'online_store', true, 'derived') ON CONFLICT DO NOTHING"
            ),
            {"t": tenant_id, "l": uci.LOCATION_ID},
        )
        _copy_frame(s, "tmp_sales", line_ddl, acc[line_cols])
        s.execute(text(
            "INSERT INTO sales_lines SELECT :t, :d, sheet, source_row, invoice, sku_id, qty, price_minor, "
            "'GBP', ts, customer_id, country FROM tmp_sales"), {"t": tenant_id, "d": dataset_id})
        _copy_frame(s, "tmp_returns", line_ddl + ", return_kind text", ret[line_cols + ["return_kind"]])
        s.execute(text(
            "INSERT INTO return_lines SELECT :t, :d, sheet, source_row, invoice, sku_id, qty, price_minor, "
            "'GBP', ts, customer_id, country, return_kind FROM tmp_returns"),
            {"t": tenant_id, "d": dataset_id})
        qframe = qua.assign(raw=qua["raw"].map(lambda r: json.dumps(r, default=str)))
        _copy_frame(s, "tmp_q", "sheet text, source_row int, reason text, raw text",
                    qframe[["sheet", "source_row", "reason", "raw"]])
        s.execute(text(
            "INSERT INTO quarantine (tenant_id, dataset_id, source_sheet, source_row, reason, raw) "
            "SELECT :t, :d, sheet, source_row, reason, raw::jsonb FROM tmp_q"),
            {"t": tenant_id, "d": dataset_id})
        _copy_frame(s, "tmp_products", "sku_id text, first_sale date, last_sale date, description text",
                    products[["sku_id", "min", "max", "description"]])
        s.execute(text(
            "INSERT INTO products (tenant_id, sku_id, description, unit, source_kind, dataset_id, "
            "first_sale, last_sale) SELECT :t, sku_id, description, 'unit', 'public', :d, first_sale, "
            "last_sale FROM tmp_products ON CONFLICT (tenant_id, sku_id) DO UPDATE SET "
            "first_sale = EXCLUDED.first_sale, last_sale = EXCLUDED.last_sale"),
            {"t": tenant_id, "d": dataset_id})
        _copy_frame(s, "tmp_daily", "sku_id text, day date, units int, location_id text",
                    daily[["sku_id", "day", "units", "location_id"]])
        s.execute(text(
            "INSERT INTO sales_daily SELECT :t, :d, sku_id, location_id, day, units FROM tmp_daily"),
            {"t": tenant_id, "d": dataset_id})
        s.execute(text(
            "INSERT INTO audit_events (tenant_id, action, entity, entity_id, detail) VALUES "
            "(:t, 'dataset.ingested', 'dataset', :d, CAST(:x AS jsonb))"),
            {"t": tenant_id, "d": str(dataset_id), "x": json.dumps(report["totals"])})
    if uci.sha256_file(zip_path) != digest:
        raise RuntimeError("Raw file changed during ingestion")
    return {"dataset_id": str(dataset_id), "reused": False, "report": report}
