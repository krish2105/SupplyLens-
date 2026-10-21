import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from supplylens.db import tenant_session
from supplylens.forecasting.service import ForecastError, run_forecast


@pytest.fixture()
def dataset(clean_db, tenant_a):
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, "
                       "bytes, schema_version, status) VALUES (:i,:t,'t','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        start = date(2011, 1, 3)
        for i in range(70):
            s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,'S1','L',:day,:u)"),
                      {"t": tenant_a, "d": did, "day": start + timedelta(days=i), "u": (i % 7) + 1})
    return did


def test_run_persists_points_and_ignores_future(dataset, tenant_a):
    origin = date(2011, 2, 27)
    run = run_forecast(tenant_a, dataset, ["S1"], origin, horizon=7)
    with tenant_session(tenant_a) as s:
        n = s.execute(text("SELECT count(*) FROM forecast_points WHERE run_id=:r"), {"r": run.run_id}).scalar()
        status = s.execute(text("SELECT status FROM forecast_runs WHERE id=:r"), {"r": run.run_id}).scalar()
    assert n == 7 and status == "SUCCEEDED"
    assert run.points["day"].min().date() == origin + timedelta(days=1)


def test_rejects_origin_after_data_and_bad_horizon(dataset, tenant_a):
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, dataset, ["S1"], date(2012, 1, 1))
    assert e.value.code == "origin_after_data"
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, dataset, ["S1"], date(2011, 2, 1), horizon=0)
    assert e.value.code == "invalid_horizon"


def test_unknown_sku_is_flagged_not_invented(dataset, tenant_a):
    run = run_forecast(tenant_a, dataset, ["S1", "NOPE"], date(2011, 2, 27), horizon=7)
    assert run.quality_flags == {"NOPE": "insufficient_history"}


def test_trained_model_cannot_replay_origins_before_its_training_cutoff(dataset, tenant_a):
    import json as _json
    with tenant_session(tenant_a) as s:
        s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, training_cutoff,
            artifact_path, artifact_sha256) VALUES (:i,:t,'lightgbm_quantile','1.0.0','CHAMPION',:d,'2011-03-01','x',:a)"""),
                  {"i": uuid.uuid4(), "t": tenant_a, "d": dataset, "a": _json.dumps([{"file": "missing.txt", "sha256": "0"}])})
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, dataset, ["S1"], date(2011, 2, 27), horizon=7)
    assert e.value.code == "model_trained_after_origin"
    # Decision flows fall back to the baseline and say so.
    run = run_forecast(tenant_a, dataset, ["S1"], date(2011, 2, 27), horizon=7, allow_baseline_fallback=True)
    assert "seasonal_naive baseline used" in run.quality_flags["_model"]


def test_untrusted_artifact_is_refused(dataset, tenant_a):
    import json as _json
    with tenant_session(tenant_a) as s:
        s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, training_cutoff,
            artifact_path, artifact_sha256) VALUES (:i,:t,'lightgbm_quantile','1.0.0','CHAMPION',:d,'2011-01-01','tests',:a)"""),
                  {"i": uuid.uuid4(), "t": tenant_a, "d": dataset,
                   "a": _json.dumps([{"file": f"lightgbm_q{q}.txt", "sha256": "deadbeef"} for q in (10, 50, 90)])})
    with pytest.raises(ForecastError) as e:
        run_forecast(tenant_a, dataset, ["S1"], date(2011, 3, 10), horizon=7)
    assert e.value.code == "artifact_untrusted"
