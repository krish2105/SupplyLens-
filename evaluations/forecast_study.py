"""Run the frozen forecasting study (ML-001..ML-008) on admitted UCI data and register models.

uv run python evaluations/forecast_study.py [--config ml/configs/forecast_study_v1.json] [--quick]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.seed import tenant_id
from supplylens_ml import models as M
from supplylens_ml.panel import save_panel
from supplylens_ml.evaluate import paired_bootstrap, score
from supplylens_ml.panel import WINDOW, actuals, build_panel, mase_scale, select_cohort


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_daily(tenant):
    with tenant_session(tenant) as s:
        ds = s.execute(text("SELECT id, sha256 FROM datasets WHERE name='UCI Online Retail II'")).first()
        rows = s.execute(text("SELECT sku_id, day, units FROM sales_daily WHERE dataset_id=:d"), {"d": ds.id}).all()
    return ds, pd.DataFrame(rows, columns=["sku_id", "day", "units"])


def origins_until(panel, start, cutoff_i, step, horizon):
    i0 = max(panel.idx(start), WINDOW)
    return [i for i in range(i0, cutoff_i - horizon + 1, step)]


def fit_predict(family, cfg, panel, cutoff_i, seed, conf, out_dir=None, tag=""):
    H = conf["horizon"]
    if family == "seasonal_naive":
        return M.seasonal_naive_panel(panel, cutoff_i, H), {}, None
    if family == "lightgbm":
        orig = origins_until(panel, conf["train_origin_start"], cutoff_i, conf["train_origin_step_days"]["lightgbm"], H)
        X, y = M.lgbm_training_set(panel, orig, H)
        t0 = time.time()
        params = {k: v for k, v in cfg.items() if k != "rounds"}
        boosters = M.train_lgbm(X, y, seed, rounds=cfg["rounds"], params=params)
        info = {"train_rows": int(len(X)), "origins": len(orig), "seconds": round(time.time() - t0, 1)}
        files = None
        if out_dir:
            files = []
            for q, b in zip((10, 50, 90), boosters):
                p = out_dir / f"lightgbm{tag}_q{q}.txt"
                b.save_model(str(p))
                files.append(p)
        return M.predict_lgbm(boosters, panel, cutoff_i, H), info, files
    if family == "tcn":
        # PyTorch runs in its own process (OpenMP runtime conflict with LightGBM).
        orig = origins_until(panel, conf["train_origin_start"], cutoff_i, conf["train_origin_step_days"]["tcn"], H)
        work = Path(conf["_work"])
        pnl, pred, info_p = work / "panel.npz", work / f"pred_{seed}.npy", work / f"info_{seed}.json"
        if not pnl.exists():
            save_panel(panel, pnl)
        model_out = (out_dir / f"tcn{tag}_seed{seed}.pt") if out_dir else work / f"tmp_seed{seed}.pt"
        cmd = [sys.executable, "-m", "supplylens_ml.tcn", "train", "--panel", str(pnl), "--index", str(cutoff_i),
               "--seed", str(seed), "--cfg", json.dumps(cfg), "--origins", json.dumps(orig), "--model-out", str(model_out),
               "--pred-out", str(pred), "--info-out", str(info_p)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-2000:])
        last = [l for l in r.stderr.splitlines() if "epoch" in l][-1:]
        log(f"tcn seed {seed} done {last}")
        info = json.loads(info_p.read_text())
        return np.load(pred), info, ([model_out] if out_dir else None)
    raise ValueError(family)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="ml/configs/forecast_study_v1.json")
    ap.add_argument("--quick", action="store_true", help="smoke run: 40 SKUs, 2 epochs; NOT a research result")
    ns = ap.parse_args()
    conf = json.loads((REPO_ROOT / ns.config).read_text())
    tenant = tenant_id("uci-research")
    ds, daily = load_daily(tenant)
    full = build_panel(daily, conf["data"]["start"], conf["data"]["end"])
    cohort = select_cohort(full, conf["cohort"]["selection_end"], conf["cohort"]["lookback_days"],
                           conf["cohort"]["min_selling_days"], max_n=40 if ns.quick else None)
    panel = full.subset(cohort)
    if ns.quick:
        for c in conf["search"]["tcn"]:
            c["epochs"] = 2
        conf["search"]["lightgbm"] = conf["search"]["lightgbm"][:1]
        conf["search"]["tcn"] = conf["search"]["tcn"][:1]
        conf["seeds"]["tcn"] = [0]
    exp_id = f"{conf['study_id']}-{'smoke-' if ns.quick else ''}{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out = REPO_ROOT / "artifacts" / "experiments" / exp_id
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    tv = subprocess.run([sys.executable, "-c", "import torch;print(torch.__version__, 'mps' if torch.backends.mps.is_available() else 'cpu')"],
                        capture_output=True, text=True).stdout.split()
    env = {"python": sys.version.split()[0], "platform": platform.platform(), "torch": tv[0], "tcn_device": tv[1],
           "lightgbm": __import__("lightgbm").__version__, "commit": commit, "hardware": "Apple M4 Pro, 24 GB"}
    conf["_work"] = str(out / "_work")
    Path(conf["_work"]).mkdir(exist_ok=True)
    log(f"study {exp_id}: {len(cohort)} SKUs, dataset {ds.sha256[:12]}, tcn device {env['tcn_device']}")
    (out / "config.json").write_text(json.dumps({k: v for k, v in conf.items() if k != "_work"}, indent=2))
    (out / "cohort.json").write_text(json.dumps(cohort))
    H = conf["horizon"]

    # ---------------- validation: model selection (test window untouched)
    val_idx = [panel.idx(d) for d in conf["validation_origins"]]
    selection = {}
    for family, grid in (("seasonal_naive", [{}]), ("lightgbm", conf["search"]["lightgbm"]), ("tcn", conf["search"]["tcn"])):
        best = None
        for ci, cfg in enumerate(grid):
            seeds = conf["seeds"].get(family, [0]) if family == "tcn" else [0]
            seeds = seeds[:1]  # selection uses seed 0; all seeds are run on the final test
            vals = []
            for vi in val_idx:
                for seed in seeds:
                    raw, info, _ = fit_predict(family, cfg, panel, vi, seed, conf)
                    s = score(raw, actuals(panel, vi, H), mase_scale(panel, vi))
                    vals.append(s["pinball_mean"])
                    log(f"val {family} cfg{ci} origin={panel.dates[vi].date()} pinball={s['pinball_mean']:.4f} mae={s['mae']:.3f} {info}")
            mean = float(np.mean(vals))
            if best is None or mean < best[1]:
                best = (ci, mean, cfg)
        selection[family] = {"config_index": best[0], "validation_pinball": best[1], "config": best[2]}
    champion = min(selection, key=lambda f: selection[f]["validation_pinball"])
    selection["champion_by_validation"] = champion
    (out / "selection.json").write_text(json.dumps(selection, indent=2))
    log(f"selection frozen: {selection}")

    # ---------------- final test: scored once with frozen choices
    ti = panel.idx(conf["test_origin"])
    y = actuals(panel, ti, H)
    ms = mase_scale(panel, ti)
    results, artifacts = {}, {}
    sn_raw, _, _ = fit_predict("seasonal_naive", {}, panel, ti, 0, conf)
    results["seasonal_naive"] = score(sn_raw, y, ms)
    raw, info, files = fit_predict("lightgbm", selection["lightgbm"]["config"], panel, ti, 0, conf, out)
    results["lightgbm"] = {**score(raw, y, ms), "train": info}
    artifacts["lightgbm"] = [{"file": f.name, "sha256": sha(f)} for f in files]
    tcn_scores = []
    for seed in conf["seeds"]["tcn"]:
        raw, info, files = fit_predict("tcn", selection["tcn"]["config"], panel, ti, seed, conf, out)
        s = {**score(raw, y, ms), "train": info, "seed": seed}
        tcn_scores.append(s)
        artifacts.setdefault("tcn", []).extend({"file": f.name, "sha256": sha(f), "seed": seed} for f in files)
        log(f"test tcn seed {seed}: pinball={s['pinball_mean']:.4f} mae={s['mae']:.3f}")
    keys = ["mae", "mase", "pinball_mean", "coverage_80", "width_80", "crossing_rate_raw"]
    results["tcn"] = {**tcn_scores[0], "seed_runs": [{k: t[k] for k in keys + ["seed"]} for t in tcn_scores],
                      "seed_mean": {k: float(np.mean([t[k] for t in tcn_scores if t[k] is not None])) for k in keys},
                      "seed_sd": {k: float(np.std([t[k] for t in tcn_scores if t[k] is not None])) for k in keys}}
    comparisons = {
        "lightgbm_vs_seasonal_naive": paired_bootstrap(results["lightgbm"]["per_series_mae"], results["seasonal_naive"]["per_series_mae"]),
        "tcn_seed0_vs_seasonal_naive": paired_bootstrap(results["tcn"]["per_series_mae"], results["seasonal_naive"]["per_series_mae"]),
        "tcn_seed0_vs_lightgbm": paired_bootstrap(results["tcn"]["per_series_mae"], results["lightgbm"]["per_series_mae"]),
    }
    summary = {f: {k: results[f][k] for k in keys + ["pinball", "mase_undefined_series"]} for f in results}
    metrics = {"experiment_id": exp_id, "smoke_run": ns.quick, "dataset_sha256": ds.sha256, "cohort_size": len(cohort),
               "test_origin": conf["test_origin"], "test_window": [str(panel.dates[ti + 1].date()), str(panel.dates[ti + H].date())],
               "selection": selection, "summary": summary, "tcn_seed_mean": results["tcn"]["seed_mean"],
               "tcn_seed_sd": results["tcn"]["seed_sd"], "comparisons": comparisons, "artifacts": artifacts, "environment": env,
               "pinball_by_horizon": {f: results[f]["pinball_by_horizon"] for f in results}}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    per = pd.DataFrame({"sku_id": cohort, **{f"mae_{f}": results[f]["per_series_mae"] for f in results}})
    per.to_csv(out / "per_series_mae.csv", index=False)
    log(f"summary: {json.dumps(summary, indent=1)}")
    log(f"comparisons: {json.dumps(comparisons, indent=1)}")

    if ns.quick:
        log("smoke run: models NOT registered")
        return
    # ---------------- registry: status follows the frozen validation rule, not the test result
    with tenant_session(tenant) as s:
        for family, ver, art in (("seasonal_naive", "1.0.0", None), ("lightgbm_quantile", "1.0.0", artifacts["lightgbm"]),
                                 ("tcn_quantile", "1.0.0", artifacts["tcn"])):
            key = {"seasonal_naive": "seasonal_naive", "lightgbm_quantile": "lightgbm", "tcn_quantile": "tcn"}[family]
            status = "CHAMPION" if key == champion else "EVALUATED"
            m = {**summary[key], "experiment_id": exp_id, "validation_pinball": selection[key]["validation_pinball"]}
            if key == "tcn":
                m["seed_mean"], m["seed_sd"] = results["tcn"]["seed_mean"], results["tcn"]["seed_sd"]
            cfg = selection[key]["config"]
            s.execute(text("""INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, training_cutoff,
                config, metrics, artifact_path, artifact_sha256, code_version) VALUES (:i,:t,:f,:v,:st,:d,:c,CAST(:cfg AS jsonb),
                CAST(:m AS jsonb),:p,:h,:code) ON CONFLICT (tenant_id, family, version) DO UPDATE SET status=EXCLUDED.status,
                training_cutoff=EXCLUDED.training_cutoff, config=EXCLUDED.config, metrics=EXCLUDED.metrics,
                artifact_path=EXCLUDED.artifact_path, artifact_sha256=EXCLUDED.artifact_sha256, code_version=EXCLUDED.code_version"""),
                {"i": uuid.uuid4(), "t": tenant, "f": family, "v": ver, "st": status, "d": ds.id, "c": conf["test_origin"],
                 "cfg": json.dumps(cfg), "m": json.dumps(m), "p": str(out.relative_to(REPO_ROOT)) if art else None,
                 "h": json.dumps(art) if art else None, "code": commit})
    log(f"registered models; champion by validation = {champion}; artifacts in {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
