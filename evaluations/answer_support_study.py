"""R3: when should supplier-document search offer an answer? Abstention, ambiguity and paraphrase robustness.

Questions are generated from the UCI workspace's simulated agreements and the Demo workspace's fictional contracts; labels
are known by construction (not human-reviewed):
  answerable        R2's frozen supplier-terms questions (scoped to the supplier), expected version and section known
  paraphrase        the same facts asked in other words ("smallest order size", "delivery time"), same expected passage
  named_supplier    unscoped questions naming a supplier; the top passage must come from that supplier
  unknown_product   R2's made-up product codes; must abstain
  out_of_scope      topics no permitted passage mentions (verified against the corpus before freezing); must abstain
  ambiguous         unscoped questions that several suppliers answer differently; must not present one answer

The task set is split in half by a hash of the task id. Thresholds are chosen on the development half (grid search,
macro accuracy over categories) and scored once on the test half, for hybrid and for lexical-only search (the hosted
demo has no embeddings). The baseline is the rule before Phase 5: answer unless a named identifier is missing.

uv run python evaluations/answer_support_study.py
"""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.knowledge import retrieve
from supplylens.knowledge.retrieve import answer_support, search
from supplylens.seed import tenant_id

TASKS = REPO_ROOT / "evaluations" / "tasksets"
TASKSET = TASKS / "r3_answer_support_v1.jsonl"
R2 = TASKS / "r2_supplier_terms_v1.jsonl"
CUT = "2011-12-08T23:59:00+00:00"
PARAPHRASES = ["smallest order size and delivery time for {sku}", "how many units must be ordered at minimum for {sku}",
               "unit price and pack multiple for {sku}", "how long does delivery take for {sku}"]
OUT_OF_SCOPE = {
    "warranty": "warranty period for {sku}", "liability": "liability cap in the {supplier} agreement",
    "force majeure": "force majeure clause in the {supplier} agreement", "termination": "termination notice period for {supplier}",
    "governing law": "governing law and jurisdiction of the {supplier} contract",
    "insurance": "insurance cover required from {supplier}", "confidentiality": "confidentiality obligations of {supplier}",
    "rebate": "volume rebate for {sku}", "audit": "audit rights over {supplier}", "penalty": "late delivery penalty for {sku}",
    "refund": "refund for damaged {sku}", "exclusivity": "exclusivity commitment of {supplier}",
}
AMBIGUOUS_UCI = ["minimum order quantity and lead time", "standard lead time from order acceptance",
                 "unit price per unit excluding VAT", "order multiples for schedule items", "minimum order quantity",
                 "lead time in calendar days"]
AMBIGUOUS_DEMO = ["minimum order quantity DEMO-REF-SKU", "lead time for DEMO-REF-SKU", "unit price of DEMO-REF-SKU"]
GRID = {"min_coverage": [0.4, 0.5, 0.6, 0.67, 0.75, 0.8, 0.9, 1.0],
        "min_similarity": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 1.01],
        "ambiguity_margin": [0.0, 0.05, 0.1, 0.2, 0.3]}


def log(m):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {m}", flush=True)


def split(task_id: str) -> str:
    return "dev" if int(hashlib.sha256(task_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def absent_topics(uci) -> dict[str, str]:
    """Keep only topics whose key word occurs in no permitted chunk of the UCI workspace."""
    keep = {}
    with tenant_session(uci) as s:
        for word, template in OUT_OF_SCOPE.items():
            n = s.execute(text("SELECT count(*) FROM chunks WHERE tsv @@ plainto_tsquery('english', :w)"), {"w": word}).scalar()
            if n == 0:
                keep[word] = template
    return keep


def build_tasks() -> list[dict]:
    uci, demo = tenant_id("uci-research"), tenant_id("demo")
    r2 = [json.loads(line) for line in R2.read_text().splitlines() if line.strip()]
    with tenant_session(uci) as s:
        suppliers = {r.supplier_id: r.name for r in s.execute(text("SELECT supplier_id, name FROM suppliers ORDER BY 1"))}
    tasks = []
    for t in r2:
        base = {"tenant": "uci-research", "effective_date": t["effective_date"], "knowledge_cutoff": t["knowledge_cutoff"]}
        if t["case"] == "unknown_product":
            tasks.append({**base, "id": f"unknown:{t['id']}", "category": "unknown_product", "query": t["query"],
                          "supplier_id": t["supplier_id"], "entities": t["entities"], "expect": "abstain"})
            continue
        tasks.append({**base, "id": f"answerable:{t['id']}", "category": "answerable", "query": t["query"],
                      "supplier_id": t["supplier_id"], "entities": t["entities"], "expect": "answer",
                      "expect_version_id": t["expect_version_id"], "expect_section": t["expect_section"]})
        if t["case"] == "current":
            sku = t["entities"][0].upper()
            for n, p in enumerate(PARAPHRASES):
                tasks.append({**base, "id": f"paraphrase:{n}:{t['id']}", "category": "paraphrase", "query": p.format(sku=sku),
                              "supplier_id": t["supplier_id"], "entities": t["entities"], "expect": "answer",
                              "expect_version_id": t["expect_version_id"], "expect_section": t["expect_section"]})
    skus = sorted({t["entities"][0].upper() for t in r2 if t["case"] == "current"})[:6]
    for word, template in absent_topics(uci).items():
        for n, (sid, name) in enumerate(sorted(suppliers.items())):
            sku = skus[n % len(skus)]
            tasks.append({"tenant": "uci-research", "id": f"oos:{word}:{sid}", "category": "out_of_scope",
                          "query": template.format(sku=sku, supplier=name), "supplier_id": sid if "{supplier}" in template else None,
                          "entities": [sku.lower()] if "{sku}" in template else [], "expect": "abstain",
                          "effective_date": "2011-12-08", "knowledge_cutoff": CUT})
    for sid, name in sorted(suppliers.items()):
        for n, tmpl in enumerate(["minimum order quantity in the {name} agreement", "standard lead time agreed with {name}"]):
            tasks.append({"tenant": "uci-research", "id": f"named:{n}:{sid}", "category": "named_supplier",
                          "query": tmpl.format(name=name), "supplier_id": None, "entities": [], "expect": "answer",
                          "expect_supplier": sid, "effective_date": "2011-12-08", "knowledge_cutoff": CUT})
    for q in AMBIGUOUS_UCI:
        tasks.append({"tenant": "uci-research", "id": f"ambiguous:uci:{q}", "category": "ambiguous", "query": q,
                      "supplier_id": None, "entities": [], "expect": "ambiguous", "effective_date": "2011-12-08",
                      "knowledge_cutoff": CUT})
    for q in AMBIGUOUS_DEMO:
        tasks.append({"tenant": "demo", "id": f"ambiguous:demo:{q}", "category": "ambiguous", "query": q, "supplier_id": None,
                      "entities": [], "expect": "ambiguous", "effective_date": "2026-10-19",
                      "knowledge_cutoff": "2026-10-19T09:00:00+00:00"})
    _ = demo
    return [{**t, "split": split(t["id"])} for t in tasks]


def judge(task: dict, res: dict, sup: dict, baseline: bool) -> bool:
    results = res["results"]
    if baseline:
        answered, ambiguous = bool(results) and not res["abstain"], False
    else:
        answered = bool(results) and not res["abstain"] and sup["supported"] and not sup["ambiguous"]
        ambiguous = sup["ambiguous"]
    if task["expect"] == "abstain":
        return not answered
    if task["expect"] == "ambiguous":
        return ambiguous or not answered
    if not answered:
        return False
    top = results[0]
    if "expect_supplier" in task:
        return top.supplier_id == task["expect_supplier"]
    return top.version_id == task["expect_version_id"] and top.section == task["expect_section"]


def run_condition(tasks, channels) -> list[tuple[dict, dict]]:
    tenants = {"uci-research": tenant_id("uci-research"), "demo": tenant_id("demo")}
    out = []
    for t in tasks:
        res = search(tenants[t["tenant"]], t["query"], as_of=datetime.fromisoformat(t["knowledge_cutoff"]), role="planner",
                     effective_date=date.fromisoformat(t["effective_date"]), mode="effective", supplier_id=t["supplier_id"],
                     entities=t["entities"], k=8, channels=channels, explain=True)
        out.append((t, res))
    return out


def score(runs, params: dict | None, split_name: str) -> dict:
    per = defaultdict(lambda: [0, 0])
    for t, res in runs:
        if t["split"] != split_name:
            continue
        si = res["support_inputs"]
        sup = answer_support(si["query_lexemes"], res["results"], si["lexemes"], entities=si["entities"], scoped=si["scoped"],
                             **(params or {})) if params else {}
        ok = judge(t, res, sup, baseline=params is None)
        per[t["category"]][0] += ok
        per[t["category"]][1] += 1
    cats = {c: {"correct": v[0], "n": v[1], "rate": v[0] / v[1]} for c, v in sorted(per.items())}
    return {"macro_accuracy": sum(c["rate"] for c in cats.values()) / len(cats), "categories": cats}


def main():
    TASKS.mkdir(parents=True, exist_ok=True)
    if not TASKSET.exists():                         # frozen on first generation
        TASKSET.write_text("\n".join(json.dumps(t) for t in build_tasks()) + "\n")
    tasks = [json.loads(line) for line in TASKSET.read_text().splitlines() if line.strip()]
    exp_id = f"R3-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out = REPO_ROOT / "artifacts" / "experiments" / exp_id
    out.mkdir(parents=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    counts = defaultdict(lambda: defaultdict(int))
    for t in tasks:
        counts[t["split"]][t["category"]] += 1
    log(f"{exp_id}: {len(tasks)} tasks {json.dumps(counts)}")
    hybrid = run_condition(tasks, ("lexical", "vector"))
    modes = {res["mode"] for _, res in hybrid}
    if modes != {"hybrid"}:
        raise SystemExit(f"embedding service unavailable (modes {modes}); R3 needs the hybrid condition")
    lexical = run_condition(tasks, ("lexical",))
    best = None
    for cov, sim, mar in itertools.product(GRID["min_coverage"], GRID["min_similarity"], GRID["ambiguity_margin"]):
        p = {"min_coverage": cov, "min_similarity": sim, "ambiguity_margin": mar}
        s = score(hybrid, p, "dev")
        key = (round(s["macro_accuracy"], 6), s["categories"].get("answerable", {}).get("rate", 0), -cov, -mar)
        if best is None or key > best[0]:
            best = (key, p, s)
    chosen = best[1]
    log(f"chosen on dev: {chosen} macro {best[2]['macro_accuracy']:.3f}")
    current = {"min_coverage": retrieve.SUPPORT_MIN_COVERAGE, "min_similarity": retrieve.SUPPORT_MIN_SIMILARITY,
               "ambiguity_margin": retrieve.AMBIGUITY_MARGIN}
    results = {
        "dev": {"baseline_hybrid": score(hybrid, None, "dev"), "chosen_hybrid": best[2]},
        "test": {"baseline_hybrid": score(hybrid, None, "test"), "chosen_hybrid": score(hybrid, chosen, "test"),
                 "baseline_lexical_only": score(lexical, None, "test"), "chosen_lexical_only": score(lexical, chosen, "test")},
    }
    metrics = {"experiment_id": exp_id, "status": "current", "commit": commit,
               "taskset": str(TASKSET.relative_to(REPO_ROOT)), "taskset_sha256": hashlib.sha256(TASKSET.read_bytes()).hexdigest(),
               "tasks": len(tasks), "counts": counts, "grid": GRID, "chosen_on_dev": chosen,
               "constants_in_code_at_run": current, "constants_match_choice": current == chosen,
               "results": results, "labels": "by construction from simulated and fictional documents; not human-reviewed"}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    (out / "config.json").write_text(json.dumps({"grid": GRID, "paraphrases": PARAPHRASES, "out_of_scope": OUT_OF_SCOPE,
                                                 "ambiguous": AMBIGUOUS_UCI + AMBIGUOUS_DEMO}, indent=2))
    for name, r in results["test"].items():
        log(f"test {name}: macro {r['macro_accuracy']:.3f} " +
            " ".join(f"{c}={v['correct']}/{v['n']}" for c, v in r["categories"].items()))
    log(f"constants in code match the dev choice: {current == chosen}")


if __name__ == "__main__":
    main()
