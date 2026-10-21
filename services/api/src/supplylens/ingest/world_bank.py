"""Ingest World Bank IPF contract awards (CC BY 4.0) into the contract-research workspace.

These are public procurement awards financed by World Bank projects. They are NOT supplier
terms for UCI products and are never joined to them.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from ..config import REPO_ROOT
from ..db import tenant_session
from .uci import _copy_frame

PATH = REPO_ROOT / "data/raw/core/world_bank_ipf_awards/awards.jsonl"
SOURCE = "https://financesone.worldbank.org/contract-awards-in-investment-project-financing-since-fy-2020/DS00005"


def _date(v):
    try:
        return datetime.strptime(v, "%d-%b-%Y").date().isoformat() if v else None
    except ValueError:
        return None


def ingest(tenant_id) -> dict:
    from supplylens_ml.uci import sha256_file
    digest = sha256_file(PATH)
    with tenant_session(tenant_id) as s:
        row = s.execute(text("SELECT id FROM datasets WHERE sha256=:h"), {"h": digest}).first()
        if row:
            return {"reused": True, "dataset_id": str(row.id)}
    rows, bad = [], 0
    with PATH.open() as f:
        for n, line in enumerate(f, start=1):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows.append({"source_row": n, "wb_contract_number": r.get("wb_contract_number"), "supplier_id": r.get("supplier_id"),
                         "supplier": (r.get("supplier") or "").strip(), "supplier_country": r.get("supplier_country"),
                         "borrower_country": r.get("borrower_country"), "region": r.get("region"),
                         "procurement_category": r.get("procurement_category"), "procurement_method": r.get("procurement_method"),
                         "project_id": r.get("project_id"), "project_name": r.get("project_name"),
                         "contract_description": (r.get("contract_description") or "")[:2000],
                         "signing_date": _date(r.get("contract_signing_date")), "fiscal_year": r.get("fiscal_year"),
                         "amount_usd": r.get("supplier_contract_amount_usd"), "review_type": r.get("review_type")})
    df = pd.DataFrame(rows)
    cols = list(df.columns)
    did = uuid.uuid4()
    report = {"rows": len(df), "unparseable_lines": bad, "missing_amount": int(df["amount_usd"].isna().sum()),
              "missing_signing_date": int(df["signing_date"].isna().sum()),
              "fiscal_years": sorted(int(x) for x in df["fiscal_year"].dropna().unique()),
              "suppliers": int(df["supplier_id"].nunique()), "total_usd": float(df["amount_usd"].fillna(0).sum()),
              "note": "Public awards; amounts in USD as published. Not stock, not lead times, not UCI suppliers."}
    with tenant_session(tenant_id) as s:
        s.execute(text("""INSERT INTO datasets (id, tenant_id, name, source_kind, license, source_url, file_name, sha256, bytes,
            schema_version, status, report) VALUES (:i,:t,'World Bank IPF contract awards','public','CC BY 4.0',:u,'awards.jsonl',
            :h,:b,'wb-awards-v1','READY',CAST(:r AS jsonb))"""),
            {"i": did, "t": tenant_id, "u": SOURCE, "h": digest, "b": PATH.stat().st_size, "r": json.dumps(report)})
        ddl = ", ".join(f"{c} {'int' if c in ('source_row', 'fiscal_year') else 'numeric' if c == 'amount_usd' else 'date' if c == 'signing_date' else 'text'}" for c in cols)
        _copy_frame(s, "tmp_awards", ddl, df[cols])
        s.execute(text(f"INSERT INTO public_awards (tenant_id, dataset_id, {', '.join(cols)}) SELECT :t, :d, {', '.join(cols)} FROM tmp_awards"),
                  {"t": tenant_id, "d": did})
    return {"reused": False, "dataset_id": str(did), **report}


if __name__ == "__main__":
    from ..seed import tenant_id
    print(json.dumps(ingest(tenant_id("contract-research")), indent=1)[:800])
