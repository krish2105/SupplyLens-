"""Time-aware resolution of supplier terms.

Two clocks matter: the knowledge cutoff (what had been received by the decision time)
and the effective date (when a term applies). A term is applicable when it was known at
the cutoff, is in force on the effective date, and is not superseded by another known,
in-force term. Two applicable terms for the same supplier/SKU without a supersession
link are a conflict: the caller must return "review required", never pick one.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from .planner import Offer


class Term(Offer):
    valid_from: date
    valid_to: date | None = None
    known_at: datetime
    supersedes: str | None = None


class Ignored(BaseModel):
    term_id: str
    supplier_id: str
    sku_id: str
    reason: str


class Resolution(BaseModel):
    applicable: list[Term]
    ignored: list[Ignored]
    conflicts: list[list[str]]


def resolve(terms: list[Term], knowledge_cutoff: datetime, effective_date: date) -> Resolution:
    ignored: list[Ignored] = []
    live: list[Term] = []
    for t in terms:
        if t.known_at > knowledge_cutoff:
            ignored.append(Ignored(term_id=t.term_id, supplier_id=t.supplier_id, sku_id=t.sku_id, reason="not known at knowledge cutoff"))
        elif t.valid_from > effective_date:
            ignored.append(Ignored(term_id=t.term_id, supplier_id=t.supplier_id, sku_id=t.sku_id, reason=f"not yet effective (from {t.valid_from})"))
        elif t.valid_to is not None and t.valid_to < effective_date:
            ignored.append(Ignored(term_id=t.term_id, supplier_id=t.supplier_id, sku_id=t.sku_id, reason=f"expired on {t.valid_to}"))
        else:
            live.append(t)
    superseded = {t.supersedes: t.term_id for t in live if t.supersedes}
    applicable = []
    for t in live:
        if t.term_id in superseded:
            ignored.append(Ignored(term_id=t.term_id, supplier_id=t.supplier_id, sku_id=t.sku_id, reason=f"superseded by {superseded[t.term_id]}"))
        else:
            applicable.append(t)
    groups: dict[tuple[str, str], list[str]] = {}
    for t in applicable:
        groups.setdefault((t.supplier_id, t.sku_id), []).append(t.term_id)
    conflicts = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    return Resolution(applicable=applicable, ignored=ignored, conflicts=conflicts)
