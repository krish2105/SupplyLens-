"""Supplier market context from World Bank IPF awards (public, observed). Read-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from ..authz import Actor
from ..db import tenant_session
from .deps import actor, csrf_guard
from .schemas import MarketSummary, SupplierDetail, SupplierHit

router = APIRouter(prefix="/api/v1/market", dependencies=[Depends(csrf_guard)])


def _has(s) -> bool:
    return bool(s.execute(text("SELECT 1 FROM public_awards LIMIT 1")).first())


@router.get("/summary", response_model=MarketSummary)
def summary(category: str | None = None, region: str | None = None, a: Actor = Depends(actor)):
    a.require("read")
    f = "WHERE (CAST(:c AS text) IS NULL OR procurement_category = :c) AND (CAST(:r AS text) IS NULL OR region = :r)"
    p = {"c": category, "r": region}
    with tenant_session(a.tenant_id) as s:
        if not _has(s):
            return {"available": False, "message": "No public award data in this workspace. Switch to Contract research."}
        ds = s.execute(text("SELECT name, license, source_url, sha256, report, created_at FROM datasets "
                            "WHERE name = 'World Bank IPF contract awards'")).mappings().first()
        by_year = s.execute(text(f"""SELECT fiscal_year, count(*) n, sum(amount_usd)::float usd FROM public_awards {f}
            GROUP BY 1 ORDER BY 1"""), p).mappings().all()
        by_cat = s.execute(text(f"""SELECT procurement_category, count(*) n, sum(amount_usd)::float usd FROM public_awards {f}
            GROUP BY 1 ORDER BY usd DESC NULLS LAST"""), p).mappings().all()
        by_region = s.execute(text(f"""SELECT region, count(*) n, sum(amount_usd)::float usd FROM public_awards {f}
            GROUP BY 1 ORDER BY usd DESC NULLS LAST"""), p).mappings().all()
        top_countries = s.execute(text(f"""SELECT supplier_country, count(*) n, sum(amount_usd)::float usd,
            count(DISTINCT supplier_id) suppliers FROM public_awards {f} GROUP BY 1 ORDER BY usd DESC NULLS LAST LIMIT 15"""), p).mappings().all()
        top_suppliers = s.execute(text(f"""SELECT supplier_id, max(supplier) supplier, max(supplier_country) country, count(*) n,
            sum(amount_usd)::float usd, count(DISTINCT borrower_country) borrower_countries FROM public_awards {f}
            GROUP BY supplier_id ORDER BY usd DESC NULLS LAST LIMIT 20"""), p).mappings().all()
        conc = s.execute(text(f"""WITH sh AS (SELECT procurement_category, supplier_id, sum(amount_usd) v FROM public_awards {f}
              GROUP BY 1, 2), tot AS (SELECT procurement_category, sum(v) t FROM sh GROUP BY 1)
            SELECT sh.procurement_category, (sum((v / NULLIF(t, 0)) ^ 2) * 10000)::float AS hhi, count(*) suppliers
            FROM sh JOIN tot USING (procurement_category) GROUP BY 1 ORDER BY 1"""), p).mappings().all()
        methods = s.execute(text(f"""SELECT procurement_method, count(*) n FROM public_awards {f} GROUP BY 1 ORDER BY n DESC LIMIT 10"""), p).mappings().all()
    return {"available": True, "dataset": dict(ds) if ds else None, "filters": p, "by_year": [dict(r) for r in by_year],
            "by_category": [dict(r) for r in by_cat], "by_region": [dict(r) for r in by_region],
            "top_supplier_countries": [dict(r) for r in top_countries], "top_suppliers": [dict(r) for r in top_suppliers],
            "concentration_hhi": [dict(r) for r in conc], "methods": [dict(r) for r in methods],
            "value_kind": "observed", "currency": "USD",
            "notes": ["Fiscal years follow the World Bank (July-June); FY2027 is partial.",
                      "HHI uses award value shares per category (0-10,000); it describes these awards, not a whole market."]}


@router.get("/suppliers", response_model=list[SupplierHit])
def suppliers(q: str, a: Actor = Depends(actor)):
    a.require("read")
    if not 2 <= len(q.strip()) <= 100:
        raise HTTPException(422, {"code": "invalid_query", "message": "search 2-100 characters"})
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT supplier_id, max(supplier) supplier, max(supplier_country) country, count(*) n,
            sum(amount_usd)::float usd, min(signing_date) first_award, max(signing_date) last_award,
            array_agg(DISTINCT procurement_category) categories FROM public_awards WHERE supplier ILIKE :q
            GROUP BY supplier_id ORDER BY usd DESC NULLS LAST LIMIT 25"""), {"q": f"%{q.strip()}%"}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/suppliers/{supplier_id}", response_model=SupplierDetail)
def supplier(supplier_id: str, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        rows = s.execute(text("""SELECT wb_contract_number, supplier, supplier_country, borrower_country, region, procurement_category,
            procurement_method, project_id, project_name, contract_description, signing_date, fiscal_year, amount_usd::float amount_usd
            FROM public_awards WHERE supplier_id = :s ORDER BY signing_date DESC LIMIT 200"""), {"s": supplier_id}).mappings().all()
    if not rows:
        raise HTTPException(404, {"code": "not_found", "message": "supplier not found"})
    return {"supplier_id": supplier_id, "awards": [dict(r) for r in rows], "value_kind": "observed"}
