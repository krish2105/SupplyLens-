"""Load supplier terms for a tenant and resolve them for a decision time."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text

from supplylens_opt.terms import Resolution, Term, resolve

from ..db import tenant_session


def load_terms(tenant_id, sku_ids: list[str], currency: str | None = None) -> list[Term]:
    with tenant_session(tenant_id) as s:
        rows = s.execute(text("""
            SELECT term_id, supplier_id, sku_id, unit_cost_minor, currency, moq, order_multiple, lead_time_days,
                   valid_from, valid_to, known_at, document_version_id, section, supersedes_term_id, value_kind
            FROM supplier_terms WHERE sku_id = ANY(:k) ORDER BY term_id"""), {"k": sku_ids}).mappings().all()
    return [Term(term_id=r["term_id"], supplier_id=r["supplier_id"], sku_id=r["sku_id"],
                 unit_cost_minor=r["unit_cost_minor"], currency=r["currency"].strip(), moq=r["moq"],
                 order_multiple=r["order_multiple"], lead_time_days=r["lead_time_days"],
                 valid_from=r["valid_from"], valid_to=r["valid_to"], known_at=r["known_at"],
                 document_version_id=str(r["document_version_id"]) if r["document_version_id"] else None,
                 section=r["section"], supersedes=r["supersedes_term_id"], value_kind=r["value_kind"])
            for r in rows if currency is None or r["currency"].strip() == currency]


def applicable_terms(tenant_id, sku_ids: list[str], knowledge_cutoff: datetime,
                     effective_date: date) -> Resolution:
    return resolve(load_terms(tenant_id, sku_ids), knowledge_cutoff, effective_date)
