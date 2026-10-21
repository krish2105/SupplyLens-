"""Research results loaded from experiment artifacts on disk (never handwritten scores)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ..authz import Actor
from ..config import REPO_ROOT
from .deps import actor, csrf_guard

router = APIRouter(prefix="/api/v1/research", dependencies=[Depends(csrf_guard)])
EXP = REPO_ROOT / "artifacts" / "experiments"


def _latest(prefix: str):
    if not EXP.exists():
        return None
    runs = sorted(p for p in EXP.iterdir() if p.name.startswith(prefix + "-") and "smoke" not in p.name
                  and (p / "metrics.json").exists())
    return runs[-1] if runs else None


@router.get("/forecast-study")
def forecast_study(a: Actor = Depends(actor)):
    a.require("read")
    if a.tenant_id is None:
        raise HTTPException(404)
    d = _latest("F1")
    if d is None:
        return {"available": False, "message": "No completed forecasting study yet. Run evaluations/forecast_study.py."}
    m = json.loads((d / "metrics.json").read_text())
    conf = json.loads((d / "config.json").read_text())
    return {"available": True, "experiment_id": m["experiment_id"], "config": conf, **m}


@router.get("/{study}")
def generic_study(study: str, a: Actor = Depends(actor)):
    a.require("read")
    if not study.replace("_", "").isalnum() or len(study) > 20:
        raise HTTPException(422, {"code": "invalid_study", "message": "unknown study"})
    d = _latest(study.upper())
    if d is None:
        return {"available": False, "message": f"No completed {study} study yet."}
    return {"available": True, **json.loads((d / "metrics.json").read_text())}
