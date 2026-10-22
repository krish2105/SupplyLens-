"""CSV onboarding: upload -> map columns -> validate (invalid rows quarantined) -> publish an immutable snapshot (audit S18).

Four canonical templates, schema version `supplylens-csv-v1`:
  sales  one row per day, SKU and location with units sold (a demand proxy: stock-outs are not visible in sales)
  stock  stock snapshot per location and SKU on a date (on hand, allocated, on order, optional capacity)
  terms  supplier terms per SKU with effective dates and the time the terms became known
  receipts  goods receipts from the ERP against reconciled SupplyLens orders (moves units from on-order to on-hand)

Every uploaded file is kept as an import batch with its SHA-256 and raw rows. Validation never edits a value silently:
a row either normalises cleanly or is quarantined with its reasons. Publishing writes the valid rows into the operational
tables in one transaction, stamps the batch with the SHA-256 of its normalised rows and freezes it (database trigger).
Nothing is invented: a workspace with only sales has no stock figures, and the interface says so.

Rights and personal data. The uploader must state the rights basis for the file. Cells that look like personal data
(email addresses, phone numbers) quarantine their row: these templates carry no personal data, so such a cell is a
mapping mistake or a file that must not be loaded.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

SCHEMA_VERSION = "supplylens-csv-v1"
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 100_000
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"^\+\d[\d ()-]{7,}\d$|^\(?\d{3}\)?[ .]\d{3}[ .-]\d{4}$")   # never matches dates or plain counts


@dataclass(frozen=True)
class Column:
    name: str
    kind: str          # date | datetime | id | text | int>=0 | int>0 | int>=1 | currency
    required: bool
    description: str
    example: str


TEMPLATES: dict[str, list[Column]] = {
    "sales": [
        Column("day", "date", True, "Calendar day of the sales (YYYY-MM-DD)", "2026-09-01"),
        Column("sku_id", "id", True, "Your product code", "SKU-1001"),
        Column("location_id", "id", True, "Store or warehouse code", "WH-01"),
        Column("units", "int>=0", True, "Units sold that day (returns excluded)", "14"),
    ],
    "stock": [
        Column("as_of", "date", True, "Snapshot date (YYYY-MM-DD)", "2026-09-30"),
        Column("location_id", "id", True, "Warehouse code", "WH-01"),
        Column("sku_id", "id", True, "Your product code", "SKU-1001"),
        Column("on_hand", "int>=0", True, "Units physically on hand", "120"),
        Column("allocated", "int>=0", False, "Units already promised to orders (default 0)", "10"),
        Column("on_order", "int>=0", False, "Units ordered and not yet received (default 0)", "40"),
        Column("capacity", "int>=0", False, "Storage capacity for this SKU at this location (blank = no limit)", "400"),
    ],
    "terms": [
        Column("term_id", "id", True, "Unique id of this term version", "SUP-A-SKU-1001-2026"),
        Column("supplier_id", "id", True, "Supplier code", "SUP-A"),
        Column("supplier_name", "text", False, "Supplier name", "Acme Components"),
        Column("sku_id", "id", True, "Your product code", "SKU-1001"),
        Column("unit_cost_minor", "int>0", True, "Unit price in minor units (pence, cents)", "450"),
        Column("currency", "currency", True, "ISO 4217 code", "GBP"),
        Column("moq", "int>=1", True, "Minimum order quantity", "50"),
        Column("order_multiple", "int>=1", True, "Order in multiples of", "10"),
        Column("lead_time_days", "int>=0", True, "Promised lead time in days", "7"),
        Column("valid_from", "date", True, "First day the term applies", "2026-01-01"),
        Column("valid_to", "date", False, "Last day the term applies (blank = open)", ""),
        Column("known_at", "datetime", True, "When the term became known (ISO 8601, UTC)", "2025-12-15T09:00:00Z"),
    ],
    # Goods receipts exported from the ERP against SupplyLens orders (audit S12): matched by the external PO number the
    # sandbox/ERP returned, booked once per receipt_id, never above the line's open quantity.
    "receipts": [
        Column("receipt_id", "id", True, "The ERP's own id for this receipt line (makes re-imports safe)", "GRN-000123-1"),
        Column("po_number", "id", True, "Purchase-order number the ERP assigned (shown on the approval)", "SBX-PO-100041"),
        Column("sku_id", "id", True, "Your product code", "SKU-1001"),
        Column("quantity", "int>0", True, "Units received", "30"),
        Column("received_on", "date", True, "Business date the goods arrived", "2026-10-24"),
        Column("location_id", "id", False, "Receiving location (needed when one order carries the SKU for several sites)", ""),
    ],
}
KEYS = {"sales": ("day", "sku_id", "location_id"), "stock": ("as_of", "location_id", "sku_id"), "terms": ("term_id",), "receipts": ("receipt_id",)}


class ImportError_(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def template_csv(kind: str) -> str:
    cols = TEMPLATES[kind]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in cols])
    w.writerow([c.example for c in cols])
    return buf.getvalue()


REDACTED = "[removed: looked like personal data]"


def _redact(value: str) -> str:
    """Cells that look like an email address or phone number are replaced BEFORE anything is stored (Phase 2,
    P2-PRIV-01): these templates carry no personal data, so such a cell is a mistake, and the row is quarantined with
    the marker instead of the value."""
    return REDACTED if (EMAIL.search(value) or PHONE.match(value)) else value


def parse(data: bytes) -> tuple[list[str], list[dict]]:
    if len(data) > MAX_BYTES:
        raise ImportError_("file_too_large", f"file is {len(data)} bytes; the limit is {MAX_BYTES}")
    try:
        txt = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportError_("not_utf8", "the file is not UTF-8 text; export it as CSV UTF-8") from None
    if "\x00" in txt:
        raise ImportError_("binary_content", "the file contains NUL characters; it is not a text CSV") from None
    try:
        dialect = csv.Sniffer().sniff(txt[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(txt), dialect=dialect)
    header = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    if not header:
        raise ImportError_("no_header", "the first line must name the columns")
    if len(set(header)) != len(header):
        raise ImportError_("duplicate_header", "two columns have the same name")
    rows = []
    try:
        for i, r in enumerate(reader):
            if i >= MAX_ROWS:
                raise ImportError_("too_many_rows", f"more than {MAX_ROWS} rows; split the file")
            rows.append({(k or "").strip(): _redact((v or "").strip()) if isinstance(v, str) else "" for k, v in r.items()})
    except csv.Error as e:          # e.g. a field over the parser's size limit or an unterminated quote
        raise ImportError_("malformed_csv", f"the file is not well-formed CSV near line {reader.line_num}: {e}") from None
    if not rows:
        raise ImportError_("empty", "the file has a header but no rows")
    return header, rows


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def suggest_mapping(kind: str, header: list[str]) -> dict[str, str | None]:
    """template column -> file column, by normalised name (exact first, then a few common synonyms)."""
    synonyms = {"day": ["date", "salesdate"], "units": ["qty", "quantity", "unitssold"], "sku_id": ["sku", "product",
                "productcode", "item"], "location_id": ["location", "store", "warehouse", "site"], "as_of": ["date",
                "snapshotdate", "asof"], "on_hand": ["onhand", "stock", "qtyonhand"], "unit_cost_minor": ["unitcost",
                "price", "cost"], "lead_time_days": ["leadtime", "leaddays"], "order_multiple": ["packsize", "multiple"]}
    by = {_norm(h): h for h in header}
    out = {}
    for c in TEMPLATES[kind]:
        hit = by.get(_norm(c.name))
        for alt in synonyms.get(c.name, []):
            hit = hit or by.get(alt)
        out[c.name] = hit
    return out


def _value(kind: str, raw: str):
    if kind == "date":
        return date.fromisoformat(raw).isoformat()
    if kind == "datetime":
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            raise ValueError("needs a time zone (for example 2026-01-01T09:00:00Z)")
        return d.astimezone(UTC).isoformat()
    if kind == "id":
        if not ID.match(raw):
            raise ValueError("codes use letters, digits and . _ : / - (max 64)")
        return raw
    if kind == "currency":
        if not re.fullmatch(r"[A-Z]{3}", raw):
            raise ValueError("use a three-letter ISO 4217 code such as GBP")
        return raw
    if kind.startswith("int"):
        if not re.fullmatch(r"-?\d+", raw):
            raise ValueError("must be a whole number")
        v = int(raw)
        floor = {"int>=0": 0, "int>0": 1, "int>=1": 1}[kind]
        if v < floor:
            raise ValueError(f"must be at least {floor}")
        if v > 2_000_000_000:
            raise ValueError("is too large")
        return v
    return raw[:200]


def validate(kind: str, mapping: dict[str, str | None], rows: list[dict]) -> list[tuple[dict | None, list[str]]]:
    cols = TEMPLATES[kind]
    missing = [c.name for c in cols if c.required and not mapping.get(c.name)]
    if missing:
        raise ImportError_("mapping_incomplete", "map the required columns: " + ", ".join(missing))
    seen: dict[tuple, int] = {}
    out = []
    for i, r in enumerate(rows):
        errors, norm = [], {}
        for c in cols:
            src = mapping.get(c.name)
            raw = r.get(src, "") if src else ""
            if raw == "":
                if c.required:
                    errors.append(f"{c.name}: required")
                norm[c.name] = 0 if c.name in ("allocated", "on_order") else None
                continue
            try:
                norm[c.name] = _value(c.kind, raw)
            except ValueError as e:
                errors.append(f"{c.name}: {e}")
        if any(isinstance(v, str) and (v == REDACTED or EMAIL.search(v) or PHONE.match(v)) for v in r.values()):
            errors.append("a cell looks like personal data (email or phone); these templates carry none")
        if not errors and kind == "terms" and norm["valid_to"] and norm["valid_to"] < norm["valid_from"]:
            errors.append("valid_to is before valid_from")
        if not errors and kind == "stock" and norm["allocated"] > norm["on_hand"] + norm["on_order"]:
            errors.append("allocated exceeds on hand plus on order")
        if not errors:
            key = tuple(norm[k] for k in KEYS[kind])
            if key in seen:
                errors.append(f"duplicate of row {seen[key] + 2} ({', '.join(KEYS[kind])})")
            else:
                seen[key] = i
        out.append((None if errors else norm, errors))
    return out


def snapshot_sha(kind: str, normalized: list[dict]) -> str:
    canon = json.dumps({"schema": f"{SCHEMA_VERSION}/{kind}", "rows": sorted(normalized, key=lambda r: json.dumps(r, sort_keys=True))},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()
