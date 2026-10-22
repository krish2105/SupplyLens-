"""Research results loaded from experiment artifacts on disk (never handwritten scores).

Headlines and status come from the committed review file evaluations/study_registry.json (audit S16): an experiment
listed there as superseded is never served as the current result, and a study without a reviewed headline says so
instead of showing a stale one.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ..authz import Actor
from ..config import REPO_ROOT
from .deps import actor, csrf_guard
from .schemas import ForecastStudyReport, Study, StudyMissing

router = APIRouter(prefix="/api/v1/research", dependencies=[Depends(csrf_guard)])
EXP = REPO_ROOT / "artifacts" / "experiments"
REGISTRY = REPO_ROOT / "evaluations" / "study_registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"experiments": {}}


def _latest(prefix: str):
    if not EXP.exists():
        return None
    reg = _registry()["experiments"]
    runs = sorted(p for p in EXP.iterdir() if p.name.startswith(prefix + "-") and "smoke" not in p.name
                  and (p / "metrics.json").exists() and reg.get(p.name, {}).get("status") != "superseded")
    return runs[-1] if runs else None


def _review(prefix: str, exp_id: str) -> dict:
    reg = _registry()["experiments"]
    r = reg.get(exp_id) or {"status": "unreviewed", "headline": None,
                            "notes": "This run has no reviewed headline yet; read the numbers, not a summary."}
    superseded = [{"experiment_id": k, **{f: v.get(f) for f in ("reason", "superseded_by")}}
                  for k, v in sorted(reg.items()) if k.startswith(prefix + "-") and v.get("status") == "superseded"]
    return {**r, "superseded": superseded}


@router.get("/forecast-study", response_model=ForecastStudyReport | StudyMissing)
def forecast_study(a: Actor = Depends(actor)):
    a.require("read")
    if a.tenant_id is None:
        raise HTTPException(404)
    d = _latest("F1")
    if d is None:
        return {"available": False, "message": "No completed forecasting study yet. Run evaluations/forecast_study.py."}
    m = json.loads((d / "metrics.json").read_text())
    conf = json.loads((d / "config.json").read_text())
    return {"available": True, "experiment_id": m["experiment_id"], "config": conf, **m, "review": _review("F1", d.name)}


@router.get("/{study}", response_model=Study)
def generic_study(study: str, a: Actor = Depends(actor)):
    a.require("read")
    if not study.replace("_", "").isalnum() or len(study) > 20:
        raise HTTPException(422, {"code": "invalid_study", "message": "unknown study"})
    d = _latest(study.upper())
    if d is None:
        return {"available": False, "message": f"No completed {study} study yet."}
    m = json.loads((d / "metrics.json").read_text())
    m.pop("results", None) if study.upper() == "AGT" else None  # per-trial detail stays in the artifact
    return {"available": True, **m, "review": _review(study.upper(), d.name)}
