"""UCI adapter tests on a tiny workbook with the publisher's layout (not real rows)."""
import zipfile

import pandas as pd
import pytest
from sqlalchemy import text

from supplylens.db import tenant_session
from supplylens.ingest.uci import ingest
from supplylens_ml import uci

ROWS = [
    # Invoice, StockCode, Description, Quantity, InvoiceDate, Price, Customer ID, Country
    ("489434", "85048", "LIGHT", "12", "2009-12-01 07:45:00", "6.95", "13085", "United Kingdom"),
    ("489434", "79323P", "PINK", "12", "2009-12-01 07:45:00", "6.75", "13085", "United Kingdom"),
    ("489434", "79323P", "PINK", "12", "2009-12-01 07:45:00", "6.75", "13085", "United Kingdom"),  # dup
    ("C489449", "22087", "PAPER", "-12", "2009-12-01 10:33:00", "2.95", "16321", "Australia"),
    ("489450", "22087", "PAPER", "-5", "2009-12-01 10:40:00", "0", "", "United Kingdom"),  # neg qty
    ("489451", "POST", "POSTAGE", "1", "2009-12-01 11:00:00", "18", "12345", "France"),
    ("489452", "21232", "MUG", "6", "not a date", "1.25", "12345", "France"),
    ("A506401", "B", "Adjust bad debt", "1", "2010-04-29 13:36:00", "-53594.36", "", "United Kingdom"),
    ("489453", "21232", "MUG", "6", "2009-12-02 09:00:00", "0", "12346", "France"),  # zero price
    ("489454", "21232", "MUG", "4", "2009-12-02 09:30:00", "1.25", "12346", "France"),
    ("489434", "85048", "LIGHT", "12", "2009-12-01 07:45:00", "6.95", "13085", "United Kingdom"),  # overlap
    ("489455", "21232", "MUG", "0", "2009-12-02 09:31:00", "1.25", "12346", "France"),
]


@pytest.fixture()
def tiny_zip(tmp_path):
    xlsx = tmp_path / "online_retail_II.xlsx"
    cols = uci.COLUMNS
    with pd.ExcelWriter(xlsx) as w:
        pd.DataFrame(ROWS[:7], columns=cols).to_excel(w, sheet_name=uci.SHEETS[0], index=False)
        pd.DataFrame(ROWS[7:], columns=cols).to_excel(w, sheet_name=uci.SHEETS[1], index=False)
    z = tmp_path / "online_retail_ii.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(xlsx, xlsx.name)
    return z


def test_every_row_has_one_disposition(tiny_zip, tmp_path):
    bronze = uci.read_bronze(tiny_zip, tmp_path / "bronze")
    c = {s: uci.classify(s, df) for s, df in bronze.items()}
    first, second = c[uci.SHEETS[0]], c[uci.SHEETS[1]]
    assert first.counts["accepted"] == 2
    assert first.counts["returned"] == 2
    assert first.counts["quarantine_reasons"] == {
        "exact_duplicate_line": 1, "non_merchandise_code": 1, "invalid_invoice_date": 1}
    assert second.counts["quarantine_reasons"] == {
        "non_merchandise_code": 1, "zero_price": 1, "zero_quantity": 1}
    kinds = sorted(first.returned["return_kind"])
    assert kinds == ["cancellation_invoice", "negative_quantity"]


def test_cross_sheet_overlap_is_counted_once(tiny_zip, tmp_path):
    bronze = uci.read_bronze(tiny_zip, tmp_path / "bronze")
    c = uci.resolve_sheet_overlap({s: uci.classify(s, df) for s, df in bronze.items()})
    second = c[uci.SHEETS[1]]
    assert second.counts["quarantine_reasons"]["cross_sheet_overlap"] == 1
    assert "489434" not in set(second.accepted["invoice"])
    assert second.counts["accepted"] == 1


def test_prices_are_integer_pence():
    assert uci._to_minor("6.95") == 695
    assert uci._to_minor("0.125") == 13
    assert uci._to_minor("abc") is None


def test_ingest_is_idempotent_and_reconciles(clean_db, tenant_a, tiny_zip, tmp_path):
    before = uci.sha256_file(tiny_zip)
    first = ingest(tenant_a, tiny_zip, tmp_path / "bronze")
    again = ingest(tenant_a, tiny_zip, tmp_path / "bronze")
    assert again["reused"] and again["dataset_id"] == first["dataset_id"]
    assert uci.sha256_file(tiny_zip) == before
    with tenant_session(tenant_a) as s:
        counts = {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                  for t in ("sales_lines", "return_lines", "quarantine", "datasets")}
        daily = s.execute(text("SELECT sku_id, day, units FROM sales_daily ORDER BY sku_id, day")).all()
    assert counts == {"sales_lines": 3, "return_lines": 2, "quarantine": 7, "datasets": 1}
    totals = first["report"]["totals"]
    assert totals["input_rows"] == totals["accepted"] + totals["returned"] + totals["quarantined"] == 12
    assert [(r.sku_id, str(r.day), r.units) for r in daily] == [
        ("21232", "2009-12-02", 4), ("79323P", "2009-12-01", 12), ("85048", "2009-12-01", 12)]


def test_ingested_rows_invisible_to_other_tenant(clean_db, tenant_a, tenant_b, tiny_zip, tmp_path):
    ingest(tenant_a, tiny_zip, tmp_path / "bronze")
    with tenant_session(tenant_b) as s:
        assert s.execute(text("SELECT count(*) FROM sales_lines")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM datasets")).scalar() == 0
