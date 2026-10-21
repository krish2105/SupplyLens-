"""Retrieval studies through the product's own search code (ARC-04, ML-006).

R1  ACORD test queries (public, expert-graded): lexical vs vector vs hybrid RRF.
R2  Time-aware supplier-terms questions generated from the UCI workspace's term records
    (simulated agreements): temporal logic OFF (knowledge cutoff only) vs ON (effective date +
    supersession), plus channel ablation, abstention on unknown products and cross-tenant probes.

The R2 answer key is written to evaluations/tasksets/ and is never read by the runtime search.

uv run python evaluations/retrieval_study.py
"""
from __future__ import annotations

import json
import math
import statistics
import subprocess
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.ingest.acord import ACORD_DIR
from supplylens.knowledge.retrieve import search
from supplylens.seed import tenant_id

TASKS = REPO_ROOT / "evaluations" / "tasksets"
FAR = datetime(2100, 1, 1, tzinfo=timezone.utc)


def log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def ndcg(ranked: list[str], gains: dict[str, int], k: int = 10) -> float:
    dcg = sum((2 ** gains.get(d, 0) - 1) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def r1():
    t = tenant_id("contract-research")
    queries = [json.loads(l) for l in (ACORD_DIR / "queries.jsonl").read_text().splitlines() if l.strip()]
    all_test = [q for q in queries if q["metadata"]["split"] == "test"]
    qrels = defaultdict(dict)
    for line in (ACORD_DIR / "qrels" / "test.tsv").read_text().splitlines()[1:]:
        qid, cid, sc = line.rsplit("\t", 2)
        qid = qid.strip('"').replace('""', '"')
        qrels[qid][cid] = int(sc)
    # Queries whose id does not match any judgement (quote-escaping differences in the source) are excluded and counted.
    test = [q for q in all_test if q["_id"] in qrels]
    unjudged = [q["_id"] for q in all_test if q["_id"] not in qrels]
    out = {}
    for cond, channels in (("lexical", ("lexical",)), ("vector", ("vector",)), ("hybrid_rrf", ("lexical", "vector"))):
        nd, rec, mrr, lat, empty = [], [], [], [], 0
        for q in test:
            gains = qrels.get(q["_id"], {})
            rel = {d for d, g in gains.items() if g >= 2}
            t0 = time.perf_counter()
            res = search(t, q["text"], as_of=FAR, role="viewer", mode="known", channels=channels, rerank=False,
                         k=10, n_candidates=50)
            lat.append((time.perf_counter() - t0) * 1000)
            ranked = [e.section for e in res["results"]]
            empty += not ranked
            nd.append(ndcg(ranked, gains))
            rec.append(len(rel & set(ranked[:10])) / min(len(rel), 10) if rel else 0.0)
            mrr.append(next((1 / (i + 1) for i, d in enumerate(ranked[:10]) if d in rel), 0.0))
        out[cond] = {"ndcg@10": statistics.mean(nd), "recall@10_rel>=2_capped": statistics.mean(rec),
                     "mrr@10": statistics.mean(mrr), "queries": len(test), "queries_no_results": empty,
                     "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95)}
        log(f"R1 {cond}: {out[cond]}")
    return {"study": "R1", "corpus": "ACORD (3,931 clauses)", "split": "test", "relevance": "graded 0-4; relevant >= 2",
            "excluded_unjudged_queries": unjudged,
            "conditions": out, "note": "Recall@10 denominator is min(#relevant, 10) per query; unjudged clauses count as 0."}


def build_r2_tasks():
    t = tenant_id("uci-research")
    with tenant_session(t) as s:
        terms = s.execute(text("""SELECT st.term_id, st.supplier_id, st.sku_id, st.valid_from, st.known_at, st.document_version_id,
            st.section, st.supersedes_term_id, sp.name FROM supplier_terms st JOIN suppliers sp ON sp.supplier_id = st.supplier_id
            WHERE st.document_version_id IS NOT NULL ORDER BY st.term_id""")).mappings().all()
    by_id = {r["term_id"]: r for r in terms}
    amended = {r["supersedes_term_id"]: r for r in terms if r["supersedes_term_id"]}
    tasks = []

    def q(case, r, eff, cutoff, expect):
        tasks.append({"id": f"{case}:{r['term_id']}:{eff}", "case": case, "query": f"minimum order quantity and lead time for {r['sku_id']}",
                      "supplier_id": r["supplier_id"], "entities": [r["sku_id"]], "effective_date": str(eff),
                      "knowledge_cutoff": cutoff, "expect_version_id": str(expect["document_version_id"]),
                      "expect_section": expect["section"], "expect_term_id": expect["term_id"]})

    for r in terms:
        if r["supersedes_term_id"]:
            continue
        new = amended.get(r["term_id"])
        if not new:
            q("current", r, date(2011, 12, 8), "2011-12-08T23:59:00+00:00", r)
            continue
        if new["valid_from"] <= date(2011, 12, 8):  # Bravo: in force at the as-of
            q("amended_in_force", r, date(2011, 12, 8), "2011-12-08T23:59:00+00:00", new)
            q("historical_before_known", r, date(2011, 11, 15), "2011-11-15T23:59:00+00:00", r)
        else:  # Alpha: known 1 Dec, effective 12 Dec
            q("known_not_in_force", r, date(2011, 12, 8), "2011-12-08T23:59:00+00:00", r)
            q("future_effective", r, date(2011, 12, 14), "2011-12-08T23:59:00+00:00", new)
            q("historical_before_known", r, date(2011, 11, 25), "2011-11-25T23:59:00+00:00", r)
    for code in ["99999Z", "00000A", "12345X", "88888B", "77777C", "55555D", "44444E", "33333F", "22222G", "11111H"]:
        tasks.append({"id": f"unknown:{code}", "case": "unknown_product", "query": f"minimum order quantity and lead time for {code}",
                      "supplier_id": "SIM-SUP-ALPHA", "entities": [code.lower()], "effective_date": "2011-12-08",
                      "knowledge_cutoff": "2011-12-08T23:59:00+00:00", "expect_abstain": True})
    return tasks


def r2():
    TASKS.mkdir(parents=True, exist_ok=True)
    path = TASKS / "r2_supplier_terms_v1.jsonl"
    if not path.exists():  # frozen on first generation
        path.write_text("\n".join(json.dumps(x) for x in build_r2_tasks()) + "\n")
    tasks = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    t, other = tenant_id("uci-research"), tenant_id("demo")
    conditions = {
        "temporal_off_hybrid": dict(mode="known", rerank=False, channels=("lexical", "vector")),
        "temporal_on_lexical": dict(mode="effective", rerank=True, channels=("lexical",)),
        "temporal_on_hybrid": dict(mode="effective", rerank=True, channels=("lexical", "vector")),
    }
    results = {}
    for name, cfg in conditions.items():
        per_case = defaultdict(lambda: {"n": 0, "top1": 0, "recall5": 0, "wrong_version_top1": 0, "abstain_ok": 0})
        lat = []
        for tk in tasks:
            t0 = time.perf_counter()
            res = search(t, tk["query"], as_of=datetime.fromisoformat(tk["knowledge_cutoff"]), role="planner",
                         effective_date=date.fromisoformat(tk["effective_date"]), supplier_id=tk["supplier_id"],
                         entities=tk["entities"], k=5, **cfg)
            lat.append((time.perf_counter() - t0) * 1000)
            c = per_case[tk["case"]]
            c["n"] += 1
            if tk.get("expect_abstain"):
                c["abstain_ok"] += int(res["abstain"])
                continue
            hits = [(e.version_id, e.section) for e in res["results"]]
            want = (tk["expect_version_id"], tk["expect_section"])
            c["top1"] += int(bool(hits) and hits[0] == want)
            c["recall5"] += int(want in hits[:5])
            c["wrong_version_top1"] += int(bool(hits) and hits[0][1] == want[1] and hits[0][0] != want[0])
        answerable = [v for k, v in per_case.items() if k != "unknown_product"]
        n = sum(v["n"] for v in answerable)
        results[name] = {
            "config": {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()},
            "answerable_questions": n,
            "top1_citation_accuracy": sum(v["top1"] for v in answerable) / n,
            "recall@5": sum(v["recall5"] for v in answerable) / n,
            "wrong_version_top1_rate": sum(v["wrong_version_top1"] for v in answerable) / n,
            "abstention_accuracy_unknown": per_case["unknown_product"]["abstain_ok"] / max(per_case["unknown_product"]["n"], 1),
            "by_case": {k: {**v, "top1_rate": v["top1"] / v["n"] if k != "unknown_product" else None} for k, v in per_case.items()},
            "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
        }
        log(f"R2 {name}: top1={results[name]['top1_citation_accuracy']:.3f} wrong_version={results[name]['wrong_version_top1_rate']:.3f} "
            f"abstain={results[name]['abstention_accuracy_unknown']:.2f}")
    # Cross-tenant probes: the same questions asked from the demo workspace must never surface UCI chunks.
    with tenant_session(t) as s:
        uci_chunks = {str(r.id) for r in s.execute(text("SELECT id FROM chunks"))}
    leaks = 0
    for tk in tasks[:60]:
        res = search(other, tk["query"], as_of=FAR, role="planner", mode="known", entities=tk["entities"], k=10)
        leaks += sum(e.chunk_id in uci_chunks for e in res["results"])
    return {"study": "R2", "taskset": str(path.relative_to(REPO_ROOT)), "questions": len(tasks),
            "generated_from": "UCI workspace supplier_terms (SIMULATED agreements); answer key not used at runtime",
            "human_reviewed": False, "conditions": results,
            "cross_tenant_probes": {"queries": 60, "leaked_chunks": leaks}}


C1_CATEGORIES = ["Minimum Commitment", "Volume Restriction", "Price Restrictions", "Exclusivity", "Termination For Convenience",
                 "Renewal Term", "Notice Period To Terminate Renewal", "Cap On Liability", "Liquidated Damages",
                 "Warranty Duration", "Audit Rights", "Insurance", "Governing Law", "Anti-Assignment", "Most Favored Nation"]


def c1():
    """Clause localisation in CUAD supply/distribution agreements: does a top-k chunk overlap the expert span?"""
    import csv
    t = tenant_id("contract-research")
    desc = {}
    with (REPO_ROOT / "data/raw/core/cuad/repository/category_descriptions.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cat = row["Category (incl. context and answer)"].replace("Category:", "").strip()
            desc[cat] = row["Description"].replace("Description:", "").strip()
    with tenant_session(t) as s:
        gold = s.execute(text("""SELECT dv.document_id, cl.version_id, cl.category, cl.char_start, cl.char_end FROM clause_labels cl
            JOIN document_versions dv ON dv.id = cl.version_id WHERE cl.category = ANY(:c)"""), {"c": C1_CATEGORIES}).all()
        chunk_span = {str(r.id): (r.char_start, r.char_end) for r in s.execute(text(
            "SELECT c.id, c.char_start, c.char_end FROM chunks c JOIN document_versions dv ON dv.id=c.version_id "
            "WHERE dv.parser_version LIKE '%cuad%'"))}
    items = defaultdict(list)
    for g in gold:
        items[(str(g.document_id), g.category)].append((g.char_start, g.char_end))
    out = {}
    for cond, channels in (("lexical", ("lexical",)), ("vector", ("vector",)), ("hybrid_rrf", ("lexical", "vector"))):
        hits = {1: 0, 3: 0, 5: 0}
        by_cat = defaultdict(lambda: [0, 0])
        for (doc, cat), spans in items.items():
            res = search(t, f"{cat}: {desc.get(cat, cat)}", as_of=FAR, role="viewer", mode="known", channels=channels,
                         rerank=False, k=5, document_id=doc, n_candidates=30)
            ranks = [chunk_span[e.chunk_id] for e in res["results"]]
            first = next((i for i, (a, z) in enumerate(ranks) if any(a < ge and z > gs for gs, ge in spans)), None)
            for k in hits:
                hits[k] += int(first is not None and first < k)
            by_cat[cat][0] += int(first is not None and first < 3)
            by_cat[cat][1] += 1
        n = len(items)
        out[cond] = {"items": n, **{f"hit@{k}": v / n for k, v in hits.items()},
                     "hit@3_by_category": {c: round(a / b, 3) for c, (a, b) in sorted(by_cat.items())}}
        log(f"C1 {cond}: hit@1={out[cond]['hit@1']:.3f} hit@3={out[cond]['hit@3']:.3f} hit@5={out[cond]['hit@5']:.3f} (n={n})")
    return {"study": "C1", "corpus": "CUAD v1 supply/distribution/manufacturing agreements (73 contracts)",
            "task": "locate expert-labelled clause category within one contract; query = CUAD category description",
            "chunking": "paragraph-packed windows of about 1,400 characters", "conditions": out}


def main():
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    import sys
    wanted = sys.argv[1:] or ["R1", "R2", "C1"]
    for name, fn in (("R1", r1), ("R2", r2), ("C1", c1)):
        if name not in wanted:
            continue
        res = fn()
        d = REPO_ROOT / "artifacts" / "experiments" / f"{name}-{stamp}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "metrics.json").write_text(json.dumps({"experiment_id": d.name, "commit": commit,
                                                    "embedding_model": "bge-m3:567m", **res}, indent=2, default=str))
        log(f"wrote {d.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
