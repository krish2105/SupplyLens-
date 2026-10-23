"""F2: segment diagnostics, segment-wise model choice and validation-fitted interval scaling on the F1 2.0.0 cohort.

Exploratory by design (ml/configs/forecast_study_f2.json): rules are fitted on the validation origins only and applied
once to the F1 test origins, which earlier protocols had already seen (D-042). Reuses F1's panel, selected
configurations and test-origin artifacts; trains only what validation needs (LightGBM and TCN seed 0 at the two
validation origins, exactly as F1's selection step did).

uv run python evaluations/forecast_segments_study.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from supplylens.config import REPO_ROOT
from supplylens_ml import models as M
from supplylens_ml.evaluate import paired_bootstrap, pinball
from supplylens_ml.panel import QUANTILES, Panel, actuals, load_panel, rearrange

sys.path.insert(0, str(REPO_ROOT / "evaluations"))
import forecast_study as F1  # F1's fit_predict: identical training code and conventions

CONFIG = REPO_ROOT / "ml" / "configs" / "forecast_study_f2.json"
GRID = np.round(np.arange(0.30, 3.0001, 0.01), 2)


def log(msg):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {msg}", flush=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ segments
def segments(panel: Panel, i: int, adi_cut: float, cv2_cut: float) -> np.ndarray:
    """Syntetos-Boylan class per series from the 365 days up to origin i (no later information)."""
    w = panel.y[max(0, i - 364): i + 1]
    out = []
    for j in range(w.shape[1]):
        col = w[:, j]
        col = col[~np.isnan(col)]
        nz = col[col > 0]
        if len(nz) < 2:
            out.append("lumpy")
            continue
        adi = len(col) / len(nz)
        cv2 = float(np.var(nz) / np.mean(nz) ** 2)
        out.append(("smooth" if cv2 < cv2_cut else "erratic") if adi < adi_cut else
                   ("intermittent" if cv2 < cv2_cut else "lumpy"))
    return np.array(out)


# ------------------------------------------------------------------------------------------------ scoring
def per_series(q: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    """q: (S, H, 3) post-processed quantiles; y: (S, H). Per-series MAE, mean pinball, coverage, below/above counts."""
    valid = ~np.isnan(y)
    nanw = lambda a: np.where(valid, a, np.nan)  # noqa: E731
    pin = np.mean([np.nanmean(nanw(pinball(y, q[..., k], t)), axis=1) for k, t in enumerate(QUANTILES)], axis=0)
    return {"mae": np.nanmean(nanw(np.abs(y - q[..., 1])), axis=1), "pinball": pin,
            "inside": np.nansum(nanw((y >= q[..., 0]) & (y <= q[..., 2])), axis=1),
            "below": np.nansum(nanw(y < q[..., 0]), axis=1), "above": np.nansum(nanw(y > q[..., 2]), axis=1),
            "points": valid.sum(axis=1), "sum_q50": np.nansum(nanw(q[..., 1]), axis=1), "sum_y": np.nansum(y, axis=1),
            "width": np.nanmean(nanw(q[..., 2] - q[..., 0]), axis=1)}


def summary(ps: dict[str, np.ndarray]) -> dict:
    pts = ps["points"].sum()
    return {"series": int(len(ps["mae"])), "mae": float(np.mean(ps["mae"])), "pinball_mean": float(np.mean(ps["pinball"])),
            "coverage_80": float(ps["inside"].sum() / pts), "below_q10": float(ps["below"].sum() / pts),
            "above_q90": float(ps["above"].sum() / pts), "width_80": float(np.mean(ps["width"])),
            "median_to_volume": float(ps["sum_q50"].sum() / ps["sum_y"].sum())}


def scaled(q: np.ndarray, s: float) -> np.ndarray:
    out = q.copy()
    out[..., 0] = np.maximum(q[..., 1] - s * (q[..., 1] - q[..., 0]), 0.0)
    out[..., 2] = q[..., 1] + s * (q[..., 2] - q[..., 1])
    return out


def coverage(q: np.ndarray, y: np.ndarray) -> float:
    valid = ~np.isnan(y)
    return float(np.mean(((y >= q[..., 0]) & (y <= q[..., 2]))[valid]))


# ------------------------------------------------------------------------------------------------ predictions
def tcn_predict(panel_path: Path, i: int, model: Path, out: Path) -> np.ndarray:
    r = subprocess.run([sys.executable, "-m", "supplylens_ml.tcn", "predict", "--panel", str(panel_path), "--index", str(i),
                        "--model", str(model), "--model-sha256", sha(model), "--pred-out", str(out)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return np.load(out)


def main():
    conf = json.loads(CONFIG.read_text())
    base = REPO_ROOT / "artifacts" / "experiments" / conf["base_experiment"]
    f1conf = json.loads((base / "config.json").read_text())
    f1metrics = json.loads((base / "metrics.json").read_text())
    selection = json.loads((base / "selection.json").read_text())
    panel_path = base / "_work" / "panel.npz"
    panel = load_panel(panel_path)
    cohort = json.loads((base / "cohort.json").read_text())
    assert panel.skus == cohort, "panel and cohort disagree"
    H = conf["horizon"]
    exp_id = f"F2-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out = REPO_ROOT / "artifacts" / "experiments" / exp_id
    work = out / "_work"
    work.mkdir(parents=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    (out / "config.json").write_text(json.dumps({**conf, "config_sha256": sha(CONFIG), "commit": commit}, indent=2))
    fconf = {**f1conf, "_work": str(work)}
    log(f"{exp_id}: {len(cohort)} products, base {conf['base_experiment']}, commit {commit[:10]}")

    # ---------------- data integrity (panel the models saw)
    y = panel.y
    integrity = {"dates": [str(panel.dates[0].date()), str(panel.dates[-1].date())], "days": len(panel.dates),
                 "contiguous_days": bool((np.diff(panel.dates.asi8) == 86_400_000_000_000).all()),
                 "negative_values": int(np.nansum(y < 0)), "missing_before_first_sale": int(np.isnan(y).sum()),
                 "zero_share_after_first_sale": float(np.nanmean(y == 0)),
                 "p99_9_daily_units": float(np.nanquantile(y, 0.999)), "max_daily_units": float(np.nanmax(y))}

    # ---------------- validation predictions (refit at each origin, as F1's selection did)
    preds: dict[tuple[str, str], np.ndarray] = {}
    for origin in conf["validation_origins"]:
        i = panel.idx(origin)
        preds[("seasonal_naive", origin)] = F1.fit_predict("seasonal_naive", {}, panel, i, 0, fconf)[0]
        preds[("lightgbm", origin)] = F1.fit_predict("lightgbm", selection["lightgbm"]["config"], panel, i, 0, fconf)[0]
        log(f"validation {origin}: lightgbm done")
        preds[("tcn", origin)] = F1.fit_predict("tcn", selection["tcn"]["config"], panel, i, conf["tcn_seed"], fconf)[0]
        log(f"validation {origin}: tcn done")

    # ---------------- test predictions from F1's saved artifacts (no refit)
    import lightgbm as lgb
    test_artifacts = {}
    for n, origin in enumerate(conf["test_origins"]):
        i = panel.idx(origin)
        tag = "" if n == len(conf["test_origins"]) - 1 else f"_o{origin}"
        preds[("seasonal_naive", origin)] = M.seasonal_naive_panel(panel, i, H)
        files = [base / f"lightgbm{tag}_q{q}.txt" for q in (10, 50, 90)]
        boosters = [lgb.Booster(model_str=f.read_text()) for f in files]
        preds[("lightgbm", origin)] = M.predict_lgbm(boosters, panel, i, H)
        model = base / f"tcn{tag}_seed{conf['tcn_seed']}.pt"
        preds[("tcn", origin)] = tcn_predict(panel_path, i, model, work / f"tcn_test_{origin}.npy")
        test_artifacts[origin] = {f.name: sha(f) for f in [*files, model]}

    # reproduction check: our test MAE must equal F1's recorded per-origin MAE
    repro = {}
    for origin in conf["test_origins"]:
        yt = actuals(panel, panel.idx(origin), H)
        for fam in conf["families"]:
            ours = float(np.mean(per_series(rearrange(preds[(fam, origin)]), yt)["mae"]))
            recorded = f1metrics["per_origin"][origin]["summary"][fam]["mae"]
            repro[f"{fam}@{origin}"] = {"ours": ours, "f1": recorded, "match": abs(ours - recorded) < 1e-6}
    log(f"reproduction of F1 test MAE: {repro}")

    # ---------------- segments and per-series scores
    seg_conf = conf["segmentation"]
    seg = {o: segments(panel, panel.idx(o), seg_conf["adi_cut"], seg_conf["cv2_cut"])
           for o in conf["validation_origins"] + conf["test_origins"]}
    scores = {(f, o): per_series(rearrange(preds[(f, o)]), actuals(panel, panel.idx(o), H))
              for (f, o) in preds}

    # ---------------- rules frozen on validation
    choice, val_seg = {}, {}
    for c in seg_conf["classes"]:
        val_seg[c] = {f: [float(x) for o in conf["validation_origins"] for x in scores[(f, o)]["pinball"][seg[o] == c]]
                      for f in conf["families"]}
        n = len(val_seg[c]["tcn"])
        choice[c] = selection["champion_by_validation"] if n < 10 else min(conf["families"], key=lambda f: np.mean(val_seg[c][f]))
    scale = {}
    for f in conf["families"]:
        qv = [rearrange(preds[(f, o)]) for o in conf["validation_origins"]]
        yv = [actuals(panel, panel.idx(o), H) for o in conf["validation_origins"]]
        covs = [np.mean([coverage(scaled(q, s), yy) for q, yy in zip(qv, yv, strict=True)]) for s in GRID]
        scale[f] = float(GRID[int(np.argmin(np.abs(np.array(covs) - 0.80)))])
    rules = {"segment_choice": choice, "interval_scale": scale,
             "validation_pinball_by_segment": {c: {f: (float(np.mean(v)) if v else None) for f, v in fs.items()}
                                                | {"series_origin_pairs": len(fs["tcn"])} for c, fs in val_seg.items()}}
    (out / "rules.json").write_text(json.dumps(rules, indent=2))
    log(f"rules frozen on validation: {rules['segment_choice']} scale {scale}")

    # ---------------- test, scored once
    variants: dict[str, dict] = {}
    rows = []
    for origin in conf["test_origins"]:
        yt = actuals(panel, panel.idx(origin), H)
        qs = {f: rearrange(preds[(f, origin)]) for f in conf["families"]}
        comp = np.stack([qs[choice[c]][j] for j, c in enumerate(seg[origin])])
        cand = {**{f: qs[f] for f in conf["families"]}, "segment_composite": comp,
                **{f"{f}_scaled": scaled(qs[f], scale[f]) for f in conf["families"]},
                "segment_composite_scaled": np.stack([scaled(qs[choice[c]][j:j + 1], scale[choice[c]])[0]
                                                      for j, c in enumerate(seg[origin])])}
        for name, q in cand.items():
            ps = per_series(q, yt)
            variants.setdefault(name, {})[origin] = {"summary": summary(ps), "per_series": ps}
        for j, sku in enumerate(panel.skus):
            rows.append({"origin": origin, "sku_id": sku, "segment": seg[origin][j],
                         **{f"mae_{f}": float(scores[(f, origin)]["mae"][j]) for f in conf["families"]},
                         **{f"pinball_{f}": float(scores[(f, origin)]["pinball"][j]) for f in conf["families"]}})
    per_seg = pd.DataFrame(rows)
    per_seg.to_csv(out / "per_segment.csv", index=False)

    def pooled(name, key):
        return np.mean([variants[name][o]["per_series"][key] for o in conf["test_origins"]], axis=0)

    test = {name: {"per_origin": {o: v[o]["summary"] for o in conf["test_origins"]},
                   "pooled_mae": float(np.mean(pooled(name, "mae"))), "pooled_pinball": float(np.mean(pooled(name, "pinball")))}
            for name, v in variants.items()}
    segtab = {}
    for c in seg_conf["classes"]:
        sub = per_seg[per_seg["segment"] == c]
        segtab[c] = {"series_origin_pairs": int(len(sub)),
                     **{f"mae_{f}": (float(sub[f"mae_{f}"].mean()) if len(sub) else None) for f in conf["families"]},
                     **{f"pinball_{f}": (float(sub[f"pinball_{f}"].mean()) if len(sub) else None) for f in conf["families"]},
                     "chosen_on_validation": choice[c]}
    comparisons = {
        "segment_composite_vs_tcn_mae": paired_bootstrap(pooled("segment_composite", "mae"), pooled("tcn", "mae")),
        "segment_composite_vs_tcn_pinball": paired_bootstrap(pooled("segment_composite", "pinball"), pooled("tcn", "pinball")),
        "tcn_scaled_vs_tcn_pinball": paired_bootstrap(pooled("tcn_scaled", "pinball"), pooled("tcn", "pinball")),
        "lightgbm_scaled_vs_lightgbm_pinball": paired_bootstrap(pooled("lightgbm_scaled", "pinball"), pooled("lightgbm", "pinball")),
    }
    val_summary = {f: {o: summary(scores[(f, o)]) for o in conf["validation_origins"]} for f in conf["families"]}
    metrics = {"experiment_id": exp_id, "status": "exploratory", "base_experiment": conf["base_experiment"],
               "dataset_sha256": f1metrics["dataset_sha256"], "cohort_size": len(cohort), "commit": commit,
               "config_sha256": sha(CONFIG), "integrity": integrity, "reproduction_of_f1_test_mae": repro,
               "rules_frozen_on_validation": {"segment_choice": choice, "interval_scale": scale},
               "validation": val_summary, "test": test, "segments_test": segtab,
               "segment_counts": {o: {c: int((seg[o] == c).sum()) for c in seg_conf["classes"]} for o in seg},
               "comparisons": comparisons, "test_artifacts_sha256": test_artifacts,
               "honesty_note": conf["test_use"]}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    log(f"done: {out.relative_to(REPO_ROOT)}")
    log(json.dumps({k: {"mae": v["pooled_mae"], "pinball": v["pooled_pinball"]} for k, v in test.items()}, indent=1))
    log(json.dumps(comparisons, indent=1))


if __name__ == "__main__":
    main()
