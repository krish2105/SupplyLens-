"""Regression tests for Phase 5 (docs/agent-handoff/phases/PHASE-05.md): forecasting lifecycle, MLOps safeguards and
answer support in retrieval. Finding IDs are in the test names."""
import hashlib
import importlib.util
import json
import shutil
import uuid
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.config import REPO_ROOT, settings
from supplylens.db import tenant_session
from supplylens.forecasting import monitor
from supplylens.forecasting.governance import promotion_problems
from supplylens.forecasting.service import BASELINE_SKU_FLAG, ForecastError, run_forecast
from supplylens.knowledge.retrieve import Evidence, answer_support
from supplylens.seed import dev_email
from supplylens.simulation import demo
from supplylens_ml.panel import Panel, build_panel, load_panel, save_panel

H = {"X-Requested-With": "supplylens"}
START = date(2011, 1, 3)
ORIGIN = date(2011, 7, 31)


# =========================================================================================== ML-P5-01 panel dates
def _panel(days=90) -> Panel:
    dates = pd.date_range("2011-01-03", periods=days, freq="D")
    return Panel(dates, ["A", "B"], np.arange(days * 2, dtype=float).reshape(days, 2))


def test_ML_P5_01_saved_panels_keep_their_calendar_and_weekdays(tmp_path):
    p = _panel()
    save_panel(p, tmp_path / "p.npz")
    back = load_panel(tmp_path / "p.npz")
    assert list(back.dates) == list(p.dates)
    assert [d.dayofweek for d in back.dates[:7]] == [0, 1, 2, 3, 4, 5, 6]
    assert back.idx("2011-02-01") == p.idx("2011-02-01")


@pytest.mark.parametrize("unit", ["us", "ns"])
def test_ML_P5_01_legacy_integer_dates_are_read_in_the_unit_they_were_written(tmp_path, unit):
    p = _panel()
    raw = p.dates.as_unit(unit).asi8              # what pandas wrote before Phase 5
    np.savez(tmp_path / "legacy.npz", dates=raw, skus=np.array(p.skus), y=p.y)
    back = load_panel(tmp_path / "legacy.npz")
    assert back.dates[0] == pd.Timestamp("2011-01-03") and back.dates[-1] == p.dates[-1]


def _in_child(code: str) -> str:
    """PyTorch runs in its own process, as in the product (LightGBM and PyTorch both bundle OpenMP: D-023)."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip()


def test_ML_P5_01_tcn_weekday_channels_vary_after_a_round_trip(tmp_path):
    if importlib.util.find_spec("torch") is None:      # checked without importing it here (D-023)
        pytest.skip("PyTorch not installed")
    save_panel(_panel(), tmp_path / "p.npz")
    out = _in_child(f"""
from supplylens_ml.panel import load_panel
from supplylens_ml.tcn import tcn_inputs
x, od, _ = tcn_inputs(load_panel({str(tmp_path / 'p.npz')!r}), 70)
print(len(set(x[0, 2:, :].argmax(axis=0).tolist())))""")
    assert out == "7"                                    # one weekday per input day; was a single constant before the fix


# =========================================================================================== P2-ML-01 trained path
@pytest.fixture()
def trained_world(clean_db, tenant_a):
    """Dataset with three long series and one young one, a tiny LightGBM champion trained on it, and its baseline row."""
    pytest.importorskip("lightgbm")
    from supplylens_ml import models as M
    did = uuid.uuid4()
    rows = []
    rng = np.random.default_rng(0)
    for k, sku in enumerate(["L1", "L2", "L3"]):
        for i in range(210):
            rows.append({"sku_id": sku, "day": START + timedelta(days=i), "units": int(5 + k + 3 * (i % 7 == 4) + rng.poisson(2))})
    for i in range(40):                                                   # a product launched 40 days before the origin
        rows.append({"sku_id": "YOUNG", "day": ORIGIN - timedelta(days=39 - i), "units": 4 + (i % 7 == 4)})
    daily = pd.DataFrame(rows)
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'t','generated','n/a','f','h',1,'v','READY')"), {"i": did, "t": tenant_a})
        s.execute(text("""INSERT INTO sales_daily (tenant_id, dataset_id, sku_id, location_id, day, units)
            SELECT :t, :d, x.sku_id, 'L', x.day, x.units FROM jsonb_to_recordset(CAST(:r AS jsonb)) AS x(sku_id text, day date, units int)"""),
                  {"t": tenant_a, "d": did, "r": daily.assign(day=daily["day"].astype(str)).to_json(orient="records")})
    panel = build_panel(daily[daily["sku_id"] != "YOUNG"], START, ORIGIN)
    origins = list(range(70, panel.idx(ORIGIN) - 27, 3))
    X, y = M.lgbm_training_set(panel, origins, 28)
    boosters = M.train_lgbm(X, y, 0, rounds=15)
    rel = f"storage_test/models_{uuid.uuid4().hex[:8]}"
    out = REPO_ROOT / rel
    out.mkdir(parents=True)
    arts = []
    for q, b in zip((10, 50, 90), boosters, strict=True):
        f = out / f"lightgbm_q{q}.txt"
        b.save_model(str(f))
        arts.append({"file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    exp = "F-TEST-20261023T000000Z"
    with tenant_session(tenant_a) as s:
        for fam, ver, status, metrics, art in (
                ("seasonal_naive", "1.0.0", "EVALUATED", {"experiment_id": exp, "validation_pinball": 9.0, "coverage_80": 0.8}, None),
                ("lightgbm_quantile", "t1", "CHAMPION",
                 {"experiment_id": exp, "validation_pinball": 5.0, "coverage_80": 0.82, "crossing_rate_raw": 0.05}, arts)):
            s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, training_cutoff,
                config, metrics, artifact_path, artifact_sha256, code_version) VALUES (:i,:t,:f,:v,:st,:d,:c,'{}'::jsonb,
                CAST(:m AS jsonb),:p,:h,'test')"""),
                {"i": uuid.uuid4(), "t": tenant_a, "f": fam, "v": ver, "st": status, "d": did, "c": ORIGIN - timedelta(days=10),
                 "m": json.dumps(metrics), "p": rel if art else None, "h": json.dumps(art) if art else None})
    yield {"dataset": did, "dir": out, "rel": rel}
    shutil.rmtree(out, ignore_errors=True)


def test_P2_ML_01_the_trained_champion_serves_forecasts_through_the_service(trained_world, tenant_a):
    run = run_forecast(tenant_a, trained_world["dataset"], ["L1", "L2", "L3"], ORIGIN, horizon=28)
    with tenant_session(tenant_a) as s:
        fam = s.execute(text("SELECT m.family FROM forecast_runs r JOIN model_versions m ON m.id = r.model_version_id "
                             "WHERE r.id = :i"), {"i": run.run_id}).scalar()
    assert fam == "lightgbm_quantile" and set(run.points["sku_id"]) == {"L1", "L2", "L3"}
    assert len(run.points) == 3 * 28 and (run.points["q10"] <= run.points["q50"]).all() and "_model" not in run.quality_flags


def test_ML_P5_02_a_product_too_young_for_the_trained_model_gets_the_baseline_not_nothing(trained_world, tenant_a):
    run = run_forecast(tenant_a, trained_world["dataset"], ["L1", "YOUNG"], ORIGIN, horizon=14)
    assert set(run.points["sku_id"]) == {"L1", "YOUNG"}
    assert run.quality_flags["YOUNG"] == BASELINE_SKU_FLAG and "L1" not in run.quality_flags


def test_P2_ML_01_an_untrusted_artifact_falls_back_to_the_baseline_and_raises_an_alert(trained_world, tenant_a):
    from supplylens.forecasting import service
    service._BOOSTERS.clear()
    (trained_world["dir"] / "lightgbm_q50.txt").write_text("tampered")
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, trained_world["dataset"], ["L1"], ORIGIN, horizon=7)
    assert e.value.code == "artifact_untrusted"
    run = run_forecast(tenant_a, trained_world["dataset"], ["L1"], ORIGIN, horizon=7, allow_baseline_fallback=True)
    assert "artifact_untrusted" in run.quality_flags["_model"] and len(run.points) == 7
    with tenant_session(tenant_a) as s:
        assert s.execute(text("SELECT count(*) FROM alerts WHERE kind = 'model_unavailable'")).scalar() >= 1


def test_P2_ML_01_a_missing_artifact_is_named_as_missing(trained_world, tenant_a):
    from supplylens.forecasting import service
    service._BOOSTERS.clear()
    (trained_world["dir"] / "lightgbm_q90.txt").unlink()
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, trained_world["dataset"], ["L1"], ORIGIN, horizon=7)
    assert e.value.code == "artifact_missing"


def test_P3_ML_02_tcn_loads_the_verified_bytes_and_refuses_a_mismatch(tmp_path):
    if importlib.util.find_spec("torch") is None:      # checked without importing it here (D-023)
        pytest.skip("PyTorch not installed")
    out = _in_child(f"""
import hashlib, torch
from supplylens_ml import tcn
f = {str(tmp_path / 'm.pt')!r}
torch.save({{"state_dict": tcn.QuantileTCN(ch=8, dropout=0.0).state_dict(), "config": {{"ch": 8, "dropout": 0.0, "epochs": 1}}}}, f)
good = hashlib.sha256(open(f, "rb").read()).hexdigest()
seen, real = [], torch.load
torch.load = lambda src, **kw: seen.append(type(src).__name__) or real(src, **kw)
tcn.load_model(f, good)
try:
    tcn.load_model(f, "0" * 64)
    refused = False
except ValueError:
    refused = True
print(seen, refused)""")
    assert out == "['BytesIO'] True"                   # built from the verified bytes; a mismatch is refused


# =========================================================================================== MLOps: gate, monitoring
def _model(tenant, family, version):
    with tenant_session(tenant) as s:
        return dict(s.execute(text("SELECT id, family, metrics, artifact_path, artifact_sha256 FROM model_versions "
                                   "WHERE family=:f AND version=:v"), {"f": family, "v": version}).mappings().first())


def test_MLOPS_P5_01_promotion_gate_passes_an_evidenced_model(trained_world, tenant_a):
    with tenant_session(tenant_a) as s:
        assert promotion_problems(s, _model(tenant_a, "lightgbm_quantile", "t1")) == []


@pytest.mark.parametrize("change,reason", [
    ({"validation_pinball": 9.5}, "does not beat the seasonal-naive baseline"),
    ({"coverage_80": 0.99}, "coverage"),
    ({"crossing_rate_raw": 0.4}, "crossing"),
    ({"experiment_id": "F1-smoke-20261021T185841Z"}, "smoke run"),
])
def test_MLOPS_P5_01_promotion_gate_refuses_weak_or_unevidenced_models(trained_world, tenant_a, change, reason):
    m = _model(tenant_a, "lightgbm_quantile", "t1")
    m["metrics"] = {**m["metrics"], **change}
    with tenant_session(tenant_a) as s:
        assert any(reason in p for p in promotion_problems(s, m))


def test_MLOPS_P5_01_promotion_gate_refuses_a_model_whose_files_are_not_here(trained_world, tenant_a):
    (trained_world["dir"] / "lightgbm_q10.txt").unlink()
    with tenant_session(tenant_a) as s:
        assert any("not on this host" in p for p in promotion_problems(s, _model(tenant_a, "lightgbm_quantile", "t1")))


def test_MLOPS_P5_01_the_promotion_route_enforces_the_gate(trained_world, tenant_a):
    with tenant_session(tenant_a) as s:
        s.execute(text("UPDATE model_versions SET metrics = metrics || '{\"validation_pinball\": 12.0}'::jsonb "
                       "WHERE family = 'lightgbm_quantile'"))
    mid = _model(tenant_a, "lightgbm_quantile", "t1")["id"]
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("tenant_admin")}, headers=H)
    r = c.post(f"/api/v1/models/{mid}/status", json={"status": "CHAMPION", "reason": "gate probe"},
               headers={**H, "X-SupplyLens-Tenant": "uci-research", "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 422 and r.json()["code"] == "promotion_gate"


def test_MLOPS_P5_02_monitoring_scores_stored_forecasts_against_sales_and_a_shadow_baseline(trained_world, tenant_a):
    origin = ORIGIN - timedelta(days=28)                       # forecasts whose days are all observed by ORIGIN
    with tenant_session(tenant_a) as s:                         # let the champion serve this older origin for the test
        s.execute(text("UPDATE model_versions SET training_cutoff = :c WHERE family='lightgbm_quantile'"), {"c": origin})
    run_forecast(tenant_a, trained_world["dataset"], ["L1", "L2", "L3"], origin, horizon=28)
    rep = monitor.report(tenant_a, trained_world["dataset"], ORIGIN)
    m = rep["models"]["lightgbm_quantile t1"]
    assert m["points"] == 3 * 28 and m["shadow_baseline_mae_same_points"] is not None and 0 <= m["coverage_80"] <= 1
    assert any("at least 200" in r for r in rep["recommendations"])      # 84 points: too few to judge, says so
    assert rep["drift"] is None or 0 <= rep["drift"]["share_above_threshold"] <= 1


def test_MLOPS_P5_02_monitoring_recommends_rollback_when_the_champion_loses_to_the_baseline(trained_world, tenant_a, monkeypatch):
    origin = ORIGIN - timedelta(days=28)
    with tenant_session(tenant_a) as s:
        s.execute(text("UPDATE model_versions SET training_cutoff = :c WHERE family='lightgbm_quantile'"), {"c": origin})
    for _ in range(3):                                          # 3 runs x 3 products x 28 days = 252 scored points
        run = run_forecast(tenant_a, trained_world["dataset"], ["L1", "L2", "L3"], origin, horizon=28)
        with tenant_session(tenant_a) as s:                     # make the stored champion forecast clearly wrong
            s.execute(text("UPDATE forecast_points SET q50 = q50 + 40, q90 = q90 + 40 WHERE run_id = :r"), {"r": run.run_id})
    rep = monitor.report(tenant_a, trained_world["dataset"], ORIGIN)
    assert rep["models"]["lightgbm_quantile t1"]["ratio_to_baseline"] > 1
    assert any("consider rolling back" in r for r in rep["recommendations"])


def test_MLOPS_P5_02_monitoring_endpoint_requires_admin_read(trained_world, tenant_a):
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("planner")}, headers=H)
    assert c.get("/api/v1/models/monitoring", headers={**H, "X-SupplyLens-Tenant": "uci-research"}).status_code == 403


# =========================================================================================== P2-KNOW-01 answer support
def _ev(cid, supplier, score, sim=None):
    return Evidence(chunk_id=cid, document_id="d", version_id="v", title="t", version_label="v1", section="s", excerpt="x",
                    char_start=0, char_end=1, valid_from=date(2011, 1, 1), valid_to=None, known_at=datetime(2011, 1, 1, tzinfo=UTC),
                    supplier_id=supplier, source_kind="generated", sha256="h", supersedes_version_id=None, score=score,
                    signals={} if sim is None else {"vector_similarity": sim})


def test_P2_KNOW_01_a_passage_covering_the_question_supports_an_answer():
    sup = answer_support({"minimum", "order", "quantiti"}, [_ev("c1", "A", 0.03)], {"c1": {"minimum", "order", "quantiti", "unit"}},
                         entities=["85123a"], scoped=True)
    assert sup["supported"] and not sup["ambiguous"]


def test_P2_KNOW_01_a_question_about_something_no_passage_mentions_is_not_answered():
    sup = answer_support({"warranti", "period"}, [_ev("c1", "A", 0.03, sim=0.9)], {"c1": {"price", "unit"}},
                         entities=[], scoped=True)
    assert not sup["supported"] and sup["unsupported_terms"] == ["period", "warranti"]


def test_P2_KNOW_01_an_unscoped_question_two_suppliers_answer_equally_is_ambiguous():
    lex = {"c1": {"lead", "time"}, "c2": {"lead", "time"}}
    sup = answer_support({"lead", "time"}, [_ev("c1", "A", 0.0330), _ev("c2", "B", 0.0329)], lex, entities=[], scoped=False)
    assert sup["ambiguous"] and sup["candidate_suppliers"] == ["A", "B"]
    scoped = answer_support({"lead", "time"}, [_ev("c1", "A", 0.0330), _ev("c2", "B", 0.0329)], lex, entities=[], scoped=True)
    assert not scoped["ambiguous"]


def test_P2_KNOW_01_the_search_route_does_not_answer_an_out_of_scope_question(clean_db, tenant_b):
    demo.load(tenant_b)
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = c.get("/api/v1/evidence/search", params={"q": "warranty period and liability cap", "supplier_id": "DEMO-REF-A",
                                                  "knowledge_cutoff": "2026-10-19T09:00:00Z", "effective_date": "2026-10-19"},
              headers={**H, "X-SupplyLens-Tenant": "demo"}).json()
    assert r["answer"]["abstained"] and not r["answer"]["claims"] and "warranti" in r["answer"]["support"]["unsupported_terms"]
    assert r["results"]                                              # related passages are still listed


def test_settings_unchanged_by_phase5_tests():
    assert settings.environment in ("development", "test")


# =========================================================================================== P3-PLAN-06
def _plan_req(offers, budget=10_000, need=10):
    from supplylens_opt.planner import Need, PlanRequest
    return PlanRequest(decision_date=date(2026, 1, 5), need_by=date(2026, 1, 12), currency="USD", budget_minor=budget,
                       needs=[Need(sku_id="A", required_units=need)], offers=offers)


def _offer(term, cost, lead):
    from supplylens_opt.planner import Offer
    return Offer(term_id=term, supplier_id=term, sku_id="A", unit_cost_minor=cost, currency="USD", moq=1, order_multiple=1,
                 lead_time_days=lead)


def test_P3_PLAN_06_an_oversized_late_offer_does_not_crash_the_infeasibility_explanation():
    from supplylens_opt.planner import plan
    r = plan(_plan_req([_offer("ok", 5_000, 2), _offer("late", 10 ** 17, 30)], budget=1_000))
    assert r.status == "INFEASIBLE" and any("could not be tested" in e for e in r.explanation)


def test_P3_PLAN_06_a_solver_timeout_is_reported_without_extra_solves(monkeypatch):
    from ortools.sat.python import cp_model

    from supplylens_opt import planner
    calls = []
    monkeypatch.setattr(planner, "_solve", lambda req, offers, relax: calls.append(relax) or (None, cp_model.UNKNOWN, {}, {}, {}))
    r = planner.plan(_plan_req([_offer("ok", 100, 2)]))
    assert r.status == "UNKNOWN" and "time limit" in r.explanation[0] and calls == [set()]
