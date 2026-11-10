"""One source for every number in the course documents (Phase 8, WP2).

Reads evaluations/study_registry.json (experiments with status "current" only) and each run's committed
artifacts/experiments/<run>/metrics.json, and writes docs/course/metrics.md and docs/course/metrics.json. Every deck,
script, report or marker guide quotes numbers only from these two files.

Deterministic: no clock, sorted output, values taken from the files as they are (metrics.md shows them to at most
four decimal places; metrics.json keeps the exact values). A value that is computed here, not read, says so in its
label ("derived"). Fails if a current run has no metrics.json or a listed field is missing.

    uv run python scripts/course_metrics.py          # write
    uv run python scripts/course_metrics.py --check  # exit 1 if the committed files are stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "evaluations" / "study_registry.json"
EXPERIMENTS = ROOT / "artifacts" / "experiments"
OUT_MD = ROOT / "docs" / "course" / "metrics.md"
OUT_JSON = ROOT / "docs" / "course" / "metrics.json"

# Kind of each number, in the brief's vocabulary: historical backtest, simulation, offline evaluation with generated
# labels, published benchmark, human-labelled, real outcome. No study has a real outcome yet.
DATA_KIND = {
    "AGT": "simulation (frozen scenarios checked by an oracle, local sandbox ERP)",
    "C1": "human-labelled (CUAD expert clause labels)",
    "D1": "simulation (generated order history)",
    "E1": "simulation (real UCI scope; terms, stock and CO2 factors assumed or simulated)",
    "F1": "historical backtest (UCI Online Retail II sales)",
    "FA1": "simulation (real UCI scope and country shares; stock, terms and budget simulated)",
    "G1": "offline evaluation with generated labels",
    "IB": "published benchmark (InventoryBench, official scorer)",
    "JS1": "simulation (assumed routes and handling times; published ft06 check)",
    "PM1": "published benchmark (AI4I 2020, a synthetic dataset) and simulation (motor fleet)",
    "QC1": "simulation (generated images)",
    "R1": "human-labelled (ACORD graded relevance judgements)",
    "R2": "offline evaluation with generated labels",
    "R3": "offline evaluation with generated labels",
    "W1": "historical backtest (UCI sales; Open-Meteo weather)",
}

# Per study: the size of the evaluation (label, path) and the key metrics (label, path). Paths are dotted keys into the
# run's metrics.json; a number in brackets indexes a list.
N = {
    "AGT": ("scenarios", "summary.scenarios"), "C1": ("(contract, category) items", "conditions.hybrid_rrf.items"),
    "D1": ("test orders", "data.orders_test"), "E1": ("products in scope", "scope.skus"),
    "F1": ("products", "cohort_size"), "FA1": ("products in scope", "scope.skus"), "G1": ("generated questions", "tasks"),
    "IB": ("benchmark instances scored", "instances"), "JS1": ("receiving-floor instances", "summary.instances"),
    "PM1": ("AI4I 2020 machine cycles", "ai4i_2020.rows"), "QC1": ("test images", "data.test"),
    "R1": ("judged test queries", "conditions.vector.queries"), "R2": ("generated questions", "questions"),
    "R3": ("generated questions (dev and test)", "tasks"), "W1": ("total-level test points", "results.total.points"),
}
METRICS = {
    "AGT": [("trials per scenario", "summary.trials_per_scenario"),
            ("verified completion rate", "summary.verified_completion_rate"),
            ("unapproved external writes", "summary.unauthorized_external_mutations")],
    "C1": [("hit@3 lexical", "conditions.lexical.hit@3"), ("hit@3 vector", "conditions.vector.hit@3"),
           ("hit@3 hybrid (RRF)", "conditions.hybrid_rrf.hit@3")],
    "D1": [("AUC supplier's past late rate", "models.supplier_late_rate.auc"),
           ("AUC logistic regression", "models.logistic_regression.auc"), ("AUC LightGBM", "models.lightgbm.auc"),
           ("training orders", "data.orders_train")],
    "E1": [("units required", "scope.required_units"),
           ("shortfall units, no CO2 cap", "exact.points[0].shortfall_units"),
           ("CO2 grams, no CO2 cap", "exact.points[0].co2_grams"),
           ("CO2 cap share, second point", "exact.points[1].cap_share"),
           ("shortfall units at that cap", "exact.points[1].shortfall_units"),
           ("NSGA-II hypervolume ratio, seed 1", "nsga2.per_seed[0].hypervolume_ratio"),
           ("NSGA-II hypervolume ratio, seed 2", "nsga2.per_seed[1].hypervolume_ratio"),
           ("NSGA-II hypervolume ratio, seed 3", "nsga2.per_seed[2].hypervolume_ratio"),
           ("exact solve seconds", "exact.seconds")],
    "F1": [("pooled MAE seasonal naive", "pooled_mae.seasonal_naive"), ("pooled MAE LightGBM", "pooled_mae.lightgbm"),
           ("pooled MAE TCN", "pooled_mae.tcn"), ("80% interval coverage TCN", "summary.tcn.coverage_80"),
           ("80% interval coverage LightGBM", "summary.lightgbm.coverage_80")],
    "FA1": [("coverage best group, no reweighing", "baseline.summary.best"),
            ("coverage worst group, no reweighing", "baseline.summary.worst"),
            ("gap points, no reweighing", "baseline.summary.gap_points"),
            ("chosen reweighing alpha", "recommended.alpha"), ("gap points at that alpha", "recommended.summary.gap_points"),
            ("worst-to-best ratio at that alpha", "recommended.summary.worst_to_best_ratio"),
            ("total coverage cost, points", "recommended.coverage_cost_points"),
            ("overall coverage at full reweighing (alpha 1)", "reweighed.overall_coverage")],
    "G1": [("answerable: facts correct rate", "categories.answerable.facts_correct.rate"),
           ("answerable: citation correct rate", "categories.answerable.citation_correct.rate"),
           ("reworded: facts correct rate", "categories.paraphrase.facts_correct.rate"),
           ("out of scope: answered when it should not be", "categories.out_of_scope.wrongly_answered"),
           ("ambiguous: answered when it should not be", "categories.ambiguous.wrongly_answered"),
           ("named supplier only: answered rate", "categories.named_supplier.answered_rate"),
           ("latency p50 seconds", "latency_seconds.p50"), ("latency p95 seconds", "latency_seconds.p95"),
           ("model", "model")],
    "IB": [("score SupplyLens policy", "policies.supplylens.overall_score"),
           ("score base-stock", "policies.base_stock.overall_score"),
           ("score last value", "policies.last_value.overall_score")],
    "JS1": [("makespan gap vs CP-SAT, FIFO", "summary.makespan_gap_vs_cp_sat.FIFO"),
            ("makespan gap vs CP-SAT, SPT", "summary.makespan_gap_vs_cp_sat.SPT"),
            ("makespan gap vs CP-SAT, EDD", "summary.makespan_gap_vs_cp_sat.EDD"),
            ("makespan gap vs CP-SAT, most work remaining", "summary.makespan_gap_vs_cp_sat.MWKR"),
            ("CP-SAT makespans proven optimal", "summary.cp_sat_proven_optimal_makespan"),
            ("ft06 known optimum", "check_ft06.known_optimum"), ("ft06 CP-SAT", "check_ft06.cp_sat")],
    "PM1": [("test failures", "ai4i_2020.test_failures"), ("AUC LightGBM", "ai4i_2020.models.lightgbm.auc"),
            ("AUC logistic regression", "ai4i_2020.models.logistic_regression.auc"),
            ("LightGBM failures caught", "ai4i_2020.models.lightgbm.policy_on_test.failures_caught"),
            ("LightGBM inspections (alerts)", "ai4i_2020.models.lightgbm.policy_on_test.alerts"),
            ("LightGBM policy cost GBP (assumed costs)", "ai4i_2020.models.lightgbm.policy_on_test.cost_gbp"),
            ("run-to-failure cost GBP (assumed costs)", "ai4i_2020.run_to_failure_cost_gbp"),
            ("fleet RUL RMSE ridge", "fleet_rul.accuracy.ridge_window_stats.rmse_all_windows"),
            ("fleet RUL RMSE 1D-CNN", "fleet_rul.accuracy.cnn.rmse_all_windows")],
    "QC1": [("test defects", "data.test_defects"), ("AUC CNN", "models.cnn.auc"),
            ("AUC hand-made features", "models.handmade_features_logistic.auc"),
            ("CNN policy recall", "models.cnn.policy.recall"), ("CNN policy escaped defects", "models.cnn.policy.escaped_defects"),
            ("CNN policy cost GBP (assumed costs)", "models.cnn.policy.cost_gbp"),
            ("inspect-everything cost GBP (assumed costs)", "inspect_everything_cost_gbp")],
    "R1": [("nDCG@10 lexical", "conditions.lexical.ndcg@10"), ("nDCG@10 vector", "conditions.vector.ndcg@10"),
           ("nDCG@10 hybrid (RRF)", "conditions.hybrid_rrf.ndcg@10")],
    "R2": [("top-1 citation accuracy, neither mechanism", "conditions.temporal_off_rerank_off.top1_citation_accuracy"),
           ("top-1 citation accuracy, both mechanisms", "conditions.temporal_on_rerank_on.top1_citation_accuracy"),
           ("main effect, effective-date filtering", "factorial.main_effect_temporal"),
           ("main effect, supersession reranking", "factorial.main_effect_rerank"),
           ("answerable questions", "conditions.temporal_on_rerank_on.answerable_questions")],
    "R3": [("test out-of-scope declined, before", "results.test.baseline_hybrid.categories.out_of_scope.correct"),
           ("test out-of-scope declined, after", "results.test.chosen_hybrid.categories.out_of_scope.correct"),
           ("test out-of-scope questions", "results.test.chosen_hybrid.categories.out_of_scope.n"),
           ("test ambiguous flagged, after", "results.test.chosen_hybrid.categories.ambiguous.correct"),
           ("test ambiguous questions", "results.test.chosen_hybrid.categories.ambiguous.n"),
           ("test reworded answered, after", "results.test.chosen_hybrid.categories.paraphrase.correct"),
           ("test reworded questions", "results.test.chosen_hybrid.categories.paraphrase.n")],
    "W1": [("WAPE seasonal naive (total units)", "results.total.models.seasonal_naive.wape"),
           ("WAPE Prophet (total units)", "results.total.models.prophet.wape"),
           ("WAPE XGBoost (total units)", "results.total.models.xgboost.wape"),
           ("RMSE XGBoost (total units)", "results.total.models.xgboost.rmse"),
           ("weather effect clear for Prophet", "results.total.weather_effect.prophet.clear"),
           ("weather effect clear for XGBoost", "results.total.weather_effect.xgboost.clear"),
           ("product-day test points", "results.skus.points")],
}


def lookup(doc: object, path: str) -> object:
    """Dotted path into a JSON document; `name[i]` indexes a list. Raises KeyError naming the missing part."""
    cur = doc
    for part in path.split("."):
        name, _, idx = part.partition("[")
        if not isinstance(cur, dict) or name not in cur:
            raise KeyError(f"{path}: no '{name}'")
        cur = cur[name]
        if idx:
            i = int(idx.rstrip("]"))
            if not isinstance(cur, list) or i >= len(cur):
                raise KeyError(f"{path}: no index {i}")
            cur = cur[i]
    return cur


def show(v: object) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if v is None:
        return "—"
    return str(v)


def build() -> dict:
    reg = json.loads(REGISTRY.read_text())
    studies = []
    for run, review in sorted(reg["experiments"].items()):
        if review.get("status") != "current":
            continue
        study = run.split("-")[0]
        path = EXPERIMENTS / run / "metrics.json"
        if not path.exists():
            raise SystemExit(f"{run} is current in the registry but {path.relative_to(ROOT)} does not exist")
        m = json.loads(path.read_text())
        if study not in METRICS or study not in DATA_KIND or study not in N:
            raise SystemExit(f"{run}: study {study} has no entry in scripts/course_metrics.py; add its data kind and metrics")
        stamp = run.split("-", 1)[1]
        n_label, n_path = N[study]
        studies.append({
            "study": study, "run_id": run, "date": f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}", "status": review["status"],
            "data_kind": DATA_KIND[study], "headline": review.get("headline", ""), "notes": review.get("notes", ""),
            "n": {"label": n_label, "value": lookup(m, n_path), "source": n_path},
            "metrics": [{"label": label, "value": lookup(m, p), "source": p} for label, p in METRICS[study]],
            "metrics_file": str(path.relative_to(ROOT)),
        })
    studies.sort(key=lambda s: s["study"])
    return {"generated_by": "scripts/course_metrics.py", "registry": str(REGISTRY.relative_to(ROOT)),
            "registry_reviewed_on": reg.get("reviewed_on"), "studies": studies,
            "not_included": sorted(k for k, v in reg["experiments"].items() if v.get("status") != "current")}


def render(doc: dict) -> str:
    out = [
        "# Course metrics: the only source for presentation numbers",
        "",
        "<!-- Generated by scripts/course_metrics.py from evaluations/study_registry.json and each run's metrics.json."
        " Do not edit by hand: run `uv run python scripts/course_metrics.py`. -->",
        "",
        "Every number in the course documents (decks, demo scripts, report, marker guide) is quoted from this file."
        " Only runs the registry marks **current** are listed; superseded and exploratory runs are named at the end"
        " and are not presentation evidence. Values are shown to at most four decimal places; exact values are in"
        " `metrics.json` next to this file. No study measures a real business outcome yet: every number below is a"
        " historical backtest, a simulation, a published benchmark, or an offline evaluation, as its data kind says.",
        "",
        f"Registry reviewed on {doc['registry_reviewed_on']}.",
        "",
        "| Study | Data kind | n | Reviewed headline | Run |",
        "|---|---|---|---|---|",
    ]
    for s in doc["studies"]:
        out.append(f"| {s['study']} | {s['data_kind']} | {show(s['n']['value'])} {s['n']['label']} | {s['headline']} |"
                   f" `{s['run_id']}` ({s['date']}) |")
    for s in doc["studies"]:
        out += ["", f"## {s['study']} — `{s['run_id']}`", "", f"Data kind: {s['data_kind']}. Source: `{s['metrics_file']}`.",
                "", f"Headline (registry review): {s['headline']}", ""]
        if s["notes"]:
            out += [f"Notes (registry review): {s['notes']}", ""]
        out += ["| Metric | Value | Field in metrics.json |", "|---|---|---|",
                f"| n: {s['n']['label']} | {show(s['n']['value'])} | `{s['n']['source']}` |"]
        out += [f"| {m['label']} | {show(m['value'])} | `{m['source']}` |" for m in s["metrics"]]
    out += ["", "## Not presentation evidence", "",
            "Superseded or exploratory runs (see the registry for the reason): "
            + ", ".join(f"`{r}`" for r in doc["not_included"]) + ".", ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    doc = build()
    md, js = render(doc), json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if "--check" in argv:
        stale = [p.relative_to(ROOT) for p, text in ((OUT_MD, md), (OUT_JSON, js)) if not p.exists() or p.read_text() != text]
        if stale:
            print("stale:", ", ".join(map(str, stale)), "— run uv run python scripts/course_metrics.py")
            return 1
        print("course metrics up to date")
        return 0
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md)
    OUT_JSON.write_text(js)
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}: {len(doc['studies'])} current studies")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
