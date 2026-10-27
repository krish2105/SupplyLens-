"""G1: are generated answers correct, cited and withheld when they should be? (F1; D-094)

The R3 task set (labels known by construction, not human-reviewed) is put to POST /api/v1/evidence/answer with a local
model (Ollama, qwen2.5:7b, temperature 0). For each task:
  answerable / paraphrase / named_supplier   was an answer generated; are the asked figures (minimum order quantity,
                                             lead time, unit price, pack multiple) the true values of the expected
                                             supplier term; does a citation point at the expected version and section
  unknown_product / out_of_scope / ambiguous  nothing may be generated
Also reported: why answers were withheld, latency, and the extractive answer on the same tasks as the baseline.
Paraphrases are sampled (every fourth, by task order); all other categories are used in full.

SUPPLYLENS_GENERATION_ENABLED=true uv run python evaluations/generation_study.py
"""
from __future__ import annotations

import json
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime

os.environ.setdefault("SUPPLYLENS_GENERATION_ENABLED", "true")

from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.config import REPO_ROOT, settings
from supplylens.db import tenant_session
from supplylens.knowledge.generate import numbers_in
from supplylens.seed import dev_email, tenant_id

TASKSET = REPO_ROOT / "evaluations" / "tasksets" / "r3_answer_support_v1.jsonl"
R2 = REPO_ROOT / "evaluations" / "tasksets" / "r2_supplier_terms_v1.jsonl"
PACE_S = 3.2          # the endpoint allows 20 answers a minute per user; a faster run measures the rate limit, not the model
MUST_ABSTAIN = {"unknown_product", "out_of_scope", "ambiguous"}
ANSWER = {"answerable", "paraphrase", "named_supplier"}


def asked(query: str) -> set[str]:
    q = query.lower()
    out = set()
    if "price" in q:
        out.add("price")
    if "multiple" in q or "pack" in q:
        out.add("multiple")
    if "minimum" in q or "smallest" in q or "how many units" in q or "moq" in q:
        out.add("moq")
    if "lead time" in q or "delivery" in q or "how long" in q:
        out.add("lead")
    return out


def r2_terms() -> dict[str, str]:
    """R3's answerable and paraphrase tasks are R2 tasks under a prefix; R2 records the expected term (the version in force,
    which for amendment and future-version cases is not the one named in the task id)."""
    return {r["id"]: r["expect_term_id"] for r in map(json.loads, R2.read_text().splitlines()) if r.get("expect_term_id")}


def term_for(tid, task, expected: dict[str, str]) -> dict | None:
    parts = task["id"].split(":")
    r2_id = ":".join(parts[2:] if task["category"] == "paraphrase" else parts[1:])
    term_id = expected.get(r2_id)
    if term_id is None:
        return None
    with tenant_session(tid) as s:
        r = s.execute(text("SELECT moq, lead_time_days, unit_cost_minor, order_multiple FROM supplier_terms WHERE term_id = :t"),
                      {"t": term_id}).mappings().first()
    return dict(r) if r else None


def facts_right(answer_text: str, want: set[str], term: dict) -> bool:
    got = numbers_in(answer_text)
    value = {"moq": str(term["moq"]), "lead": str(term["lead_time_days"]), "multiple": str(term["order_multiple"]),
             "price": f"{term['unit_cost_minor'] / 100:.2f}"}
    return all(value[f] in got for f in want)


def main() -> None:
    tasks = [json.loads(line) for line in TASKSET.read_text().splitlines() if line.strip()]
    para = [t for t in tasks if t["category"] == "paraphrase"]
    chosen = [t for t in tasks if t["category"] != "paraphrase"] + para[::4]
    clients = {}
    rows = []
    expected = r2_terms()
    last = 0.0
    for n, t in enumerate(chosen):
        time.sleep(max(0.0, PACE_S - (time.time() - last)))
        last = time.time()
        c = clients.get(t["tenant"])
        if c is None:
            c = clients[t["tenant"]] = TestClient(app)
            c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")},
                   headers={"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": t["tenant"]})
        body = {"q": t["query"], "supplier_id": t.get("supplier_id") if t["category"] in ("answerable", "paraphrase") else None,
                "effective_date": t["effective_date"], "knowledge_cutoff": t["knowledge_cutoff"]}
        t0 = time.time()
        r = c.post("/api/v1/evidence/answer", json=body,
                   headers={"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": t["tenant"]})
        if r.status_code != 200:
            raise SystemExit(f"{t['id']}: HTTP {r.status_code} {r.text[:200]}")      # never score a failed request
        d = r.json()
        g = d.get("generated") or {}
        text_out = " ".join(s["sentence"] for s in g.get("sentences", []))
        row = {"id": t["id"], "category": t["category"], "generation": d.get("generation"), "seconds": round(time.time() - t0, 2),
               "reason": d.get("message") if d.get("generation") != "answered" else None, "answer": text_out}
        if t["category"] in ANSWER and d.get("generation") == "answered":
            cited = {g["citations"][i - 1]["version_id"] + "|" + g["citations"][i - 1]["section"]
                     for s in g["sentences"] for i in s["cites"]}
            if t.get("expect_version_id"):
                row["citation_correct"] = f"{t['expect_version_id']}|{t['expect_section']}" in cited
            term = term_for(tenant_id(t["tenant"]), t, expected)
            want = asked(t["query"])
            if term and want:
                row["facts_correct"] = facts_right(text_out, want, term)
        ex = d.get("extractive") or {}
        if t["category"] in ANSWER and ex.get("claims") and t.get("expect_version_id"):
            cit = ex["claims"][0]["citation"]
            row["extractive_citation_correct"] = cit["version_id"] == t["expect_version_id"] and cit["section"] == t["expect_section"]
        rows.append(row)
        if n % 25 == 0:
            print(f"{n}/{len(chosen)} {t['category']}: {row['generation']} ({row['seconds']}s)", flush=True)

    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)

    def rate(xs, key):
        v = [x[key] for x in xs if key in x]
        return {"n": len(v), "rate": round(sum(v) / len(v), 4) if v else None}

    cats = {}
    for cat, xs in sorted(by.items()):
        gen = Counter(x["generation"] for x in xs)
        cats[cat] = {"n": len(xs), "generation": dict(gen),
                     "answered_rate": round(gen.get("answered", 0) / len(xs), 4),
                     "facts_correct": rate(xs, "facts_correct"), "citation_correct": rate(xs, "citation_correct"),
                     "extractive_citation_correct": rate(xs, "extractive_citation_correct")}
        if cat in MUST_ABSTAIN:
            cats[cat]["wrongly_answered"] = gen.get("answered", 0)
    withheld = Counter((x["reason"] or "")[:60] for x in rows if x["generation"] == "withheld")
    lat = sorted(x["seconds"] for x in rows if x["generation"] in ("answered", "withheld"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"G1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    answered = [x for x in rows if x["category"] in ANSWER and x["generation"] == "answered"]
    metrics = {
        "experiment_id": out.name, "study": "G1", "kind": "measured on synthetic tasks",
        "question": "Are generated answers correct and cited, and is nothing generated where no passage answers?",
        "model": settings.generation_model, "taskset": TASKSET.name, "tasks": len(rows),
        "categories": cats,
        "overall": {"answered_facts_correct": rate(answered, "facts_correct"), "answered_citation_correct": rate(answered, "citation_correct"),
                    "must_abstain_wrongly_answered": sum(c.get("wrongly_answered", 0) for c in cats.values()),
                    "must_abstain_tasks": sum(c["n"] for k, c in cats.items() if k in MUST_ABSTAIN)},
        "withheld_reasons": dict(withheld.most_common(8)),
        "latency_seconds": {"p50": statistics.median(lat) if lat else None, "p95": lat[int(0.95 * (len(lat) - 1))] if lat else None},
        "limits": ["labels known by construction from simulated and fictional agreements, not human-reviewed",
                   "fact check: the asked figures appear in the answer (a correct figure next to a wrong one would pass)",
                   "one local 7B model at temperature 0; paraphrases sampled one in four"],
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps({"model": settings.generation_model, "paraphrase_sample": "every 4th"}, indent=1))
    (out / "rows.json").write_text(json.dumps(rows, indent=1, default=str))
    print(json.dumps({k: metrics[k] for k in ("experiment_id", "overall", "latency_seconds", "withheld_reasons")}, indent=1))
    print(json.dumps({k: {f: v[f] for f in ("n", "answered_rate", "facts_correct", "citation_correct")} for k, v in cats.items()}, indent=1))


if __name__ == "__main__":
    main()
