"""UCI Online Retail II adapter: bronze extraction and deterministic row classification.

Source facts (UCI dataset 502, CC BY 4.0): one UK online retailer, Dec 2009 - Dec 2011,
two sheets, prices in GBP, invoices starting with "C" are cancellations, Country is the
customer's residence (never a warehouse).

Every input row ends in exactly one disposition:
  accepted    - a merchandise sale with positive quantity and positive price
  returned    - cancellation invoice ("C...") or negative-quantity adjustment
  quarantined - kept out of modelling with an explicit reason
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

TRANSFORM_VERSION = "uci-v1"
SHEETS = ("Year 2009-2010", "Year 2010-2011")
COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
           "Customer ID", "Country"]
# Merchandise codes are five digits with an optional short letter suffix (e.g. 85123A).
MERCH_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
LOCATION_ID = "UCI-ONLINE"
CURRENCY = "GBP"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_bronze(zip_path: Path, bronze_root: Path) -> dict[str, pd.DataFrame]:
    """Extract the publisher XLSX once into parquet (all columns as strings), keyed by hash.

    The raw ZIP is only read. Bronze keeps source text so silver typing is reproducible.
    """
    digest = sha256_file(zip_path)
    out_dir = bronze_root / digest[:16]
    paths = {s: out_dir / (s.replace(" ", "_") + ".parquet") for s in SHEETS}
    if all(p.exists() for p in paths.values()):
        return {s: pd.read_parquet(p) for s, p in paths.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        xlsx = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if len(xlsx) != 1:
            raise ValueError(f"Expected one XLSX in archive, found {xlsx}")
        with zf.open(xlsx[0]) as fh:
            frames = pd.read_excel(fh, sheet_name=list(SHEETS), dtype=str)
    for sheet, df in frames.items():
        missing = set(COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"Sheet {sheet} missing columns {sorted(missing)}")
        df = df[COLUMNS].copy()
        df.insert(0, "source_row", np.arange(2, len(df) + 2, dtype=np.int32))  # Excel row numbers
        df.to_parquet(paths[sheet], index=False)
        frames[sheet] = df
    return {s: frames[s] for s in SHEETS}


def _to_minor(price: str) -> int | None:
    try:
        d = Decimal(price)
    except Exception:
        return None
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class Classified:
    accepted: pd.DataFrame
    returned: pd.DataFrame
    quarantined: pd.DataFrame
    counts: dict = field(default_factory=dict)


def classify(sheet: str, raw: pd.DataFrame) -> Classified:
    """Type and classify one bronze sheet. Pure function of its input."""
    df = raw.copy()
    df["sheet"] = sheet
    df["invoice"] = df["Invoice"].fillna("").str.strip()
    df["sku_id"] = df["StockCode"].fillna("").str.strip().str.upper()
    df["qty"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["ts"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    df["price_minor"] = df["Price"].map(lambda p: _to_minor(p) if isinstance(p, str) else None)
    df["customer_id"] = df["Customer ID"].where(df["Customer ID"].notna(), None)
    df["customer_id"] = df["customer_id"].map(
        lambda c: str(int(float(c))) if isinstance(c, str) and c.strip() else None
    )
    df["country"] = df["Country"]
    df["description"] = df["Description"].fillna("").str.strip()

    reason = pd.Series(pd.NA, index=df.index, dtype="object")

    def flag(mask, why):
        nonlocal reason
        reason = reason.mask(reason.isna() & mask, why)

    flag(df["invoice"] == "", "missing_invoice")
    flag(df["sku_id"] == "", "missing_stock_code")
    flag(df["ts"].isna(), "invalid_invoice_date")
    flag(df["qty"].isna() | (df["qty"] % 1 != 0), "invalid_quantity")
    flag(df["price_minor"].isna(), "invalid_price")
    flag(df["qty"] == 0, "zero_quantity")
    flag(~df["sku_id"].str.match(MERCH_CODE), "non_merchandise_code")
    is_cancel = df["invoice"].str.startswith("C")
    is_negative = df["qty"] < 0
    # Bad-debt adjustments ("A" invoices) carry negative prices and are not sales.
    flag(df["price_minor"] < 0, "negative_price_adjustment")
    flag(~is_cancel & ~is_negative & (df["price_minor"] == 0), "zero_price")

    pending = reason.isna()
    returned_mask = pending & (is_cancel | is_negative)
    sale_mask = pending & ~returned_mask
    # Exact duplicate sale lines: keep the first occurrence, quarantine the rest.
    key = ["invoice", "sku_id", "qty", "ts", "price_minor", "customer_id", "description"]
    dup = df[sale_mask].duplicated(subset=key, keep="first")
    dup_idx = dup[dup].index
    reason.loc[dup_idx] = "exact_duplicate_line"
    sale_mask.loc[dup_idx] = False

    keep_cols = ["sheet", "source_row", "invoice", "sku_id", "description", "qty", "ts",
                 "price_minor", "customer_id", "country"]
    accepted = df.loc[sale_mask, keep_cols].copy()
    returned = df.loc[returned_mask, keep_cols].copy()
    returned["return_kind"] = np.where(
        returned["invoice"].str.startswith("C"), "cancellation_invoice", "negative_quantity"
    )
    quarantined = df.loc[reason.notna(), ["sheet", "source_row"]].copy()
    quarantined["reason"] = reason[reason.notna()]
    bad = raw.loc[reason.notna(), COLUMNS].astype(object)
    quarantined["raw"] = bad.where(bad.notna(), None).to_dict(orient="records")
    for frame in (accepted, returned):
        frame["qty"] = frame["qty"].astype("int64")
        frame["price_minor"] = frame["price_minor"].astype("int64")
    counts = {
        "input_rows": int(len(df)),
        "accepted": int(len(accepted)),
        "returned": int(len(returned)),
        "quarantined": int(len(quarantined)),
        "quarantine_reasons": {k: int(v) for k, v in quarantined["reason"].value_counts().items()},
    }
    assert counts["accepted"] + counts["returned"] + counts["quarantined"] == counts["input_rows"]
    return Classified(accepted, returned, quarantined, counts)


def resolve_sheet_overlap(classified: dict[str, Classified]) -> dict[str, Classified]:
    """The publisher's two sheets overlap (1-9 Dec 2010 appears in both).

    An invoice present in an earlier sheet is authoritative there; its rows in later
    sheets move to quarantine as `cross_sheet_overlap` so no sale is counted twice.
    """
    seen: set[str] = set()
    out: dict[str, Classified] = {}
    for sheet in SHEETS:
        c = classified[sheet]
        moved = []
        frames = {}
        for name in ("accepted", "returned"):
            frame = getattr(c, name)
            overlap = frame["invoice"].isin(seen)
            moved.append(frame.loc[overlap, ["sheet", "source_row"]])
            frames[name] = frame.loc[~overlap]
        moved_df = pd.concat(moved)
        if len(moved_df):
            moved_df = moved_df.assign(reason="cross_sheet_overlap", raw=[{} for _ in range(len(moved_df))])
        quarantined = pd.concat([c.quarantined, moved_df], ignore_index=True)
        counts = dict(c.counts)
        counts.update(accepted=len(frames["accepted"]), returned=len(frames["returned"]),
                      quarantined=len(quarantined),
                      quarantine_reasons={k: int(v) for k, v in quarantined["reason"].value_counts().items()})
        assert counts["accepted"] + counts["returned"] + counts["quarantined"] == counts["input_rows"]
        out[sheet] = Classified(frames["accepted"], frames["returned"], quarantined, counts)
        seen |= set(c.accepted["invoice"]) | set(c.returned["invoice"])
    return out


def daily_units(accepted: pd.DataFrame) -> pd.DataFrame:
    """Gold target: fulfilled positive units per SKU per business day (Europe/London local)."""
    g = accepted.assign(day=accepted["ts"].dt.date).groupby(["sku_id", "day"], as_index=False)["qty"].sum()
    g["location_id"] = LOCATION_ID
    return g.rename(columns={"qty": "units"})


def qualification_report(zip_path: Path, classified: dict[str, Classified]) -> dict:
    acc = pd.concat([c.accepted for c in classified.values()])
    ret = pd.concat([c.returned for c in classified.values()])
    revenue_minor = int((acc["qty"] * acc["price_minor"]).sum())
    return {
        "dataset": "UCI Online Retail II",
        "doi": "10.24432/C5CG6D",
        "license": "CC BY 4.0",
        "transform_version": TRANSFORM_VERSION,
        "source_file": zip_path.name,
        "sha256": sha256_file(zip_path),
        "bytes": zip_path.stat().st_size,
        "sheets": {s: c.counts for s, c in classified.items()},
        "totals": {
            "input_rows": sum(c.counts["input_rows"] for c in classified.values()),
            "accepted": len(acc),
            "returned": len(ret),
            "quarantined": sum(c.counts["quarantined"] for c in classified.values()),
            "accepted_units": int(acc["qty"].sum()),
            "accepted_value_minor_gbp": revenue_minor,
            "returned_units": int(ret["qty"].sum()),
        },
        "date_span": [str(acc["ts"].min()), str(acc["ts"].max())],
        "distinct_skus_accepted": int(acc["sku_id"].nunique()),
        "distinct_customers": int(acc["customer_id"].nunique()),
        "missing_customer_id_rows": int(acc["customer_id"].isna().sum()),
        "notes": [
            "Target is fulfilled positive units (unit-sales), not unconstrained demand.",
            "Country is customer residence, not a warehouse; one location UCI-ONLINE is used.",
            "Returns are stored separately and not netted against sales.",
            "Exact duplicate sale lines keep the first occurrence; the rest are quarantined.",
            "Prices converted to integer pence with ROUND_HALF_UP; source has at most 3 decimals.",
        ],
    }
