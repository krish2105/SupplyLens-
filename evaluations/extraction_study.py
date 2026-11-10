"""X1: how well does rule-based contract-term extraction find what CUAD's experts labelled? (Phase 8 WP7, week 8)

Data: CUAD v1 (CC BY 4.0), the 73 supply / distribution / manufacturing agreements the product already ingests
(title contains SUPPLY, DISTRIBUT or MANUFACTUR, as supplylens.ingest.cuad and study C1), 2,176 expert labels.
Only the labels of the mapped categories below are scored. The file is read directly; no database is needed.

Methods
  rules         supplylens.knowledge.extract (the product's extractor): deterministic regular expressions.
  lexical_top1  pure-Python BM25 over the contract's own paragraphs (blank-line separated; paragraphs over 2,800
  lexical_top3  characters cut into 1,400-character pieces); the query for a field is the CUAD category name and
                description, as in C1; the top k paragraphs are the predicted spans. It cannot abstain.
No embedding model is installed locally (Ollama lists only qwen2.5:7b), so there is no vector baseline here; C1 measured
vector and hybrid retrieval on the same contracts earlier. The generation model is not used for extraction (not run).

Matching (per field, per contract; a prediction is one span, a gold label is one expert span)
  overlap    the spans share at least one character
  jaccard50  CUAD's own rule (repository evaluate.py get_jaccard, reimplemented): word-set Jaccard >= 0.5, and for
             Parties also "gold text is inside the prediction". Like CUAD's evaluation it compares texts, not
             positions: a party name or date found where the experts labelled another occurrence of it still matches
  exact      the same character span, ignoring surrounding whitespace and punctuation
  precision = matched predictions / predictions; recall = matched gold spans / gold spans.
Overall: micro (pooled counts over the scored fields) and macro (mean of per-field values).

Held-out check: the rules were written by the developer after reading about ten random expert labels per category
from these same 73 contracts (and tuned against their scores), so scores on the 73 are in-sample. The other 437 CUAD
contracts (other contract types, never looked at while writing the rules) are scored once with the same code as a
held-out check.

uv run python evaluations/extraction_study.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime

from supplylens.config import REPO_ROOT
from supplylens.knowledge.extract import (
    EXTRACTOR_VERSION,
    FIELDS,
    MAX_PARTIES,
    MAX_PER_FIELD,
    extract,
)

CUAD = REPO_ROOT / "data/raw/core/cuad/extracted/data/CUADv1.json"
CATEGORIES_CSV = REPO_ROOT / "data/raw/core/cuad/repository/category_descriptions.csv"
KEYWORDS = ("SUPPLY", "DISTRIBUT", "MANUFACTUR")          # same selection as supplylens.ingest.cuad and C1

MAPPING = {
    "parties": "Parties",
    "agreement_date": "Agreement Date",
    "effective_date": "Effective Date",
    "expiry_date": "Expiration Date",
    "renewal": "Renewal Term",
    "termination_for_convenience": "Termination For Convenience",
    "exclusivity": "Exclusivity",
    "minimum_commitment": "Minimum Commitment",
    "price": "Price Restrictions",
}
NOT_SCORED = {
    "moq": "no CUAD category of its own: CUAD folds per-order minimums into Minimum Commitment, which is scored "
           "through minimum_commitment; the moq field returns the quantity only",
    "lead_time": "no CUAD category for delivery lead time",
}
MAPPING_NOTES = {
    "price": "approximate: CUAD 'Price Restrictions' labels only restrictions on changing prices; the price field also "
             "returns price amounts, which CUAD does not label, so its precision against this category understates it",
    "effective_date": "CUAD labels the effective date separately from the agreement date; both are scored separately",
}
UNMAPPED_CUAD = ["Notice Period To Terminate Renewal", "Volume Restriction", "and the 27 other CUAD categories"]

K1, B = 1.5, 0.75
STOP = set("""a an and are as at be by for from has have in is it its of on or shall that the this to under was were will
with which who whom any all each other such than then there these those may must not no nor so if into upon per""".split())
_PARA = re.compile(r"\S[\s\S]*?(?=\n\s*\n|\Z)")
_TOKEN = re.compile(r"[a-z0-9]+")
_PUNCT = " \t\n.,;:\"'“”‘’()[]"


def log(m):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {m}", flush=True)


# --------------------------------------------------------------------------------------------- data
def load_contracts():
    data = json.loads(CUAD.read_text())["data"]
    picked, other = [], []
    mismatched = 0
    for d in data:
        para = d["paragraphs"][0]
        body = para["context"]
        gold: dict[str, list[tuple[int, int]]] = {}
        for qa in para["qas"]:
            cat = qa["id"].split("__")[-1]
            for ans in qa["answers"]:
                a = ans["answer_start"]
                z = a + len(ans["text"])
                if body[a:z] != ans["text"]:
                    mismatched += 1
                gold.setdefault(cat, []).append((a, z))
        row = {"title": d["title"].strip(), "text": body, "gold": gold}
        (picked if any(k in d["title"].upper() for k in KEYWORDS) else other).append(row)
    return picked, other, mismatched


def descriptions() -> dict[str, str]:
    out = {}
    with CATEGORIES_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cat = row["Category (incl. context and answer)"].replace("Category:", "").strip()
            out[cat] = row["Description"].replace("Description:", "").strip()
    return out


# --------------------------------------------------------------------------------------------- lexical baseline
def paragraphs(body: str) -> list[tuple[int, int]]:
    out = []
    for m in _PARA.finditer(body):
        a, z = m.start(), m.end()
        while z > a and body[z - 1].isspace():
            z -= 1
        while z - a > 2_800:
            out.append((a, a + 1_400))
            a += 1_400
        if z > a:
            out.append((a, z))
    return out


def tokens(s: str) -> list[str]:
    return [w for w in _TOKEN.findall(s.lower()) if len(w) > 1 and w not in STOP]


def bm25_top(body: str, spans: list[tuple[int, int]], query: str, k: int) -> list[tuple[int, int]]:
    docs = [tokens(body[a:z]) for a, z in spans]
    if not docs:
        return []
    n = len(docs)
    avgdl = sum(map(len, docs)) / n or 1.0
    df = Counter(w for d in docs for w in set(d))
    q = set(tokens(query))
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for w in q:
            if tf[w]:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * (K1 + 1) / (tf[w] + K1 * (1 - B + B * len(d) / avgdl))
        if s > 0:
            scored.append((-s, i))
    return [spans[i] for _, i in sorted(scored)[:k]]


# --------------------------------------------------------------------------------------------- matching
def _trim(body: str, a: int, z: int) -> tuple[int, int]:
    while a < z and body[a] in _PUNCT:
        a += 1
    while z > a and body[z - 1] in _PUNCT:
        z -= 1
    return a, z


def cuad_jaccard(gt: str, pred: str) -> float:
    """CUAD repository evaluate.py get_jaccard, reimplemented without numpy."""
    for t in (".", ",", ";", ":"):
        gt, pred = gt.replace(t, ""), pred.replace(t, "")
    g = set(gt.lower().replace("/", " ").split(" "))
    p = set(pred.lower().replace("/", " ").split(" "))
    return len(g & p) / len(g | p)


def matches(body, pred, gold, how, parties=False) -> bool:
    (a, z), (ga, gz) = pred, gold
    if how == "overlap":
        return a < gz and z > ga
    if how == "exact":
        t = _trim(body, ga, gz)
        return t[1] > t[0] and _trim(body, a, z) == t
    pt, gt = body[a:z], body[ga:gz]
    return cuad_jaccard(gt, pt) >= 0.5 or (parties and gt in pt)


HOW = ("overlap", "jaccard50", "exact")


def _prf(mp, np_, mg, ng):
    p = mp / np_ if np_ else None
    r = mg / ng if ng else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": _r(p), "recall": _r(r), "f1": _r(f)}


def _r(x):
    return None if x is None else round(x, 4)


def score(contracts, predict) -> dict:
    """predict(contract, field) -> list of spans. Returns per-field and overall metrics."""
    per_field, pooled = {}, {h: [0, 0, 0, 0] for h in HOW}
    for field, cat in MAPPING.items():
        c = {h: [0, 0, 0, 0] for h in HOW}          # matched preds, preds, matched gold, gold
        with_label = detected = without_label = predicted_anyway = 0
        for ct in contracts:
            body, gold = ct["text"], ct["gold"].get(cat, [])
            preds = predict(ct, field)
            for h in HOW:
                mp = sum(any(matches(body, p, g, h, field == "parties") for g in gold) for p in preds)
                mg = sum(any(matches(body, p, g, h, field == "parties") for p in preds) for g in gold)
                for i, v in enumerate((mp, len(preds), mg, len(gold))):
                    c[h][i] += v
            if gold:
                with_label += 1
                detected += any(matches(body, p, g, "overlap") for p in preds for g in gold)
            else:
                without_label += 1
                predicted_anyway += bool(preds)
        per_field[field] = {
            "cuad_category": cat, "gold_spans": c["overlap"][3], "predictions": c["overlap"][1],
            **{h: _prf(*c[h]) for h in HOW},
            "contracts_with_label": with_label,
            "contract_hit_rate": _r(detected / with_label) if with_label else None,
            "contracts_without_label": without_label,
            "false_alarm_rate": _r(predicted_anyway / without_label) if without_label else None,
        }
        for h in HOW:
            for i in range(4):
                pooled[h][i] += c[h][i]
    overall = {}
    for h in HOW:
        macro = {}
        for m in ("precision", "recall", "f1"):
            xs = [per_field[f][h][m] for f in MAPPING if per_field[f][h][m] is not None]
            macro[m] = _r(sum(xs) / len(xs)) if xs else None
        overall[h] = {"micro": _prf(*pooled[h]), "macro": macro}
    return {"per_field": per_field, "overall": overall}


# --------------------------------------------------------------------------------------------- run
def run(contracts, desc):
    cache = {}

    def rules(ct, field):
        key = id(ct)
        if key not in cache:
            cache[key] = extract(ct["text"])
        return [(f.start, f.end) for f in cache[key] if f.field == field]

    para_cache = {}

    def lexical(k):
        def predict(ct, field):
            key = id(ct)
            if key not in para_cache:
                para_cache[key] = paragraphs(ct["text"])
            cat = MAPPING[field]
            return bm25_top(ct["text"], para_cache[key], f"{cat}: {desc.get(cat, cat)}", k)
        return predict

    return {"rules": score(contracts, rules), "lexical_top1": score(contracts, lexical(1)),
            "lexical_top3": score(contracts, lexical(3))}


def reshape(res):
    """{method: {per_field, overall}} -> per_field[field][method] and overall[method]."""
    per_field = {f: {"cuad_category": MAPPING[f], "gold_spans": res["rules"]["per_field"][f]["gold_spans"],
                     "contracts_with_label": res["rules"]["per_field"][f]["contracts_with_label"],
                     **{m: {k: v for k, v in res[m]["per_field"][f].items()
                            if k not in ("cuad_category", "gold_spans", "contracts_with_label")} for m in res}}
                 for f in MAPPING}
    return per_field, {m: res[m]["overall"] for m in res}


def main():
    t0 = time.time()
    held_out = "--no-held-out" not in sys.argv
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "services/api/src/supplylens/knowledge/extract.py",
                                 "evaluations/extraction_study.py"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip())
    picked, other, mismatched = load_contracts()
    desc = descriptions()
    labels = sum(len(v) for c in picked for v in c["gold"].values())
    log(f"X1: {len(picked)} contracts, {labels} expert labels ({len(other)} other CUAD contracts held out)")
    res = run(picked, desc)
    per_field, overall = reshape(res)
    for f in MAPPING:
        row = per_field[f]
        log(f"{f:28s} gold={row['gold_spans']:4d}  rules P/R overlap={row['rules']['overlap']['precision']}/"
            f"{row['rules']['overlap']['recall']}  lexical@1={row['lexical_top1']['overlap']['precision']}/"
            f"{row['lexical_top1']['overlap']['recall']}  lexical@3={row['lexical_top3']['overlap']['precision']}/"
            f"{row['lexical_top3']['overlap']['recall']}")
    for m, o in overall.items():
        log(f"overall {m}: overlap micro P/R={o['overlap']['micro']['precision']}/{o['overlap']['micro']['recall']} "
            f"macro P/R={o['overlap']['macro']['precision']}/{o['overlap']['macro']['recall']}  "
            f"exact micro R={o['exact']['micro']['recall']}")
    ho = None
    if held_out:
        hres = run(other, desc)
        hp, hoall = reshape(hres)
        ho = {"contracts": len(other), "labels_scored": sum(len(c["gold"].get(cat, [])) for c in other for cat in MAPPING.values()),
              "note": "CUAD contracts outside the 73 (other contract types); the rules were not read against these",
              "per_field": hp, "overall": hoall}
        for m, o in hoall.items():
            log(f"held-out {m}: overlap micro P/R={o['overlap']['micro']['precision']}/{o['overlap']['micro']['recall']}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"X1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    scored = sum(per_field[f]["gold_spans"] for f in MAPPING)
    metrics = {
        "experiment_id": out.name, "study": "X1", "kind": "human-labelled (CUAD expert labels)",
        "question": "On 73 real supply, distribution and manufacturing contracts, how many of the clauses and fields that "
                    "CUAD's experts labelled does a rule-based extractor find, with what precision, and how does that "
                    "compare with picking the top BM25 paragraphs for each field?",
        "commit": commit, "uncommitted_changes_in_method_files": dirty,
        "data": {"source": "CUAD v1 (CC BY 4.0), data/raw/core/cuad/extracted/data/CUADv1.json",
                 "selection": "title contains SUPPLY, DISTRIBUT or MANUFACTUR (as ingest/cuad.py and C1)",
                 "contracts": len(picked), "labels": labels, "labels_in_scored_categories": scored,
                 "label_offset_mismatches": mismatched},
        "mapping": {f: MAPPING[f] for f in MAPPING} | {f: None for f in NOT_SCORED},
        "mapping_notes": MAPPING_NOTES | NOT_SCORED, "cuad_categories_not_scored": UNMAPPED_CUAD,
        "methods": {
            "rules": {"code": "services/api/src/supplylens/knowledge/extract.py", "version": EXTRACTOR_VERSION,
                      "max_per_field": MAX_PER_FIELD, "max_parties": MAX_PARTIES, "can_abstain": True},
            "lexical_topk": {"k": [1, 3], "scoring": f"BM25 k1={K1} b={B}, idf over the contract's own paragraphs",
                             "units": "blank-line paragraphs; over 2,800 characters cut into 1,400-character pieces",
                             "query": "CUAD category name + description (category_descriptions.csv), as in C1",
                             "tokens": "lower-case alphanumeric, small stop-word list, no stemming", "can_abstain": False},
            "vector_or_model": "not run: no embedding model installed locally (Ollama lists only qwen2.5:7b); "
                               "generation-model extraction not attempted in X1",
        },
        "matching": {"overlap": "spans share at least one character",
                     "jaccard50": "CUAD evaluate.py rule: word-set Jaccard >= 0.5 (Parties: or gold text inside the "
                                  "prediction); compares texts, not positions, as CUAD's own evaluation does",
                     "exact": "the same character span, ignoring surrounding whitespace and punctuation",
                     "precision": "matched predictions / predictions", "recall": "matched gold spans / gold spans",
                     "contract_hit_rate": "contracts with a label where at least one prediction overlaps a gold span",
                     "false_alarm_rate": "contracts without a label where the method still returned a span"},
        "per_field": per_field, "overall": overall, "held_out_check": ho,
        "limits": [
            "in-sample: the rules were written after reading about ten expert labels per category from these 73 "
            "contracts and adjusted against their scores; the held-out check on the other CUAD contracts is the "
            "fairer estimate, but those are other contract types",
            "overlap is lenient: a whole paragraph that touches a one-line label counts as a match; exact and "
            "jaccard50 are reported to show how far the spans are from the experts' spans",
            "the lexical baseline always returns k paragraphs, so its precision falls with label rarity and its "
            "false-alarm rate is 100% wherever a term appears in the text",
            "price is scored against Price Restrictions (only 13 labels in 5 contracts); moq and lead_time are not "
            "scored because CUAD has no matching category (checked only on the fictional demo contracts in "
            "tests/test_extraction.py)",
            "English, SEC-filed contracts in plain text; no PDF or OCR intake was measured (uploads stay plain text, "
            "D-076)",
            "one annotator team's labels (CUAD); no inter-annotator agreement is reported here",
            "no embedding model and no generation model were used",
        ],
        "seconds": round(time.time() - t0, 1),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (out / "config.json").write_text(json.dumps({
        "study": "X1", "created_at": datetime.now(UTC).isoformat(), "commit": commit,
        "cuad_json_sha256": hashlib.sha256(CUAD.read_bytes()).hexdigest(),
        "categories_csv_sha256": hashlib.sha256(CATEGORIES_CSV.read_bytes()).hexdigest(),
        "selection_keywords": list(KEYWORDS), "mapping": MAPPING, "fields_extracted": list(FIELDS),
        "extractor_version": EXTRACTOR_VERSION, "bm25": {"k1": K1, "b": B}, "k": [1, 3], "stopwords": sorted(STOP),
        "held_out_check": held_out, "python": platform.python_version(),
        "command": "uv run python evaluations/extraction_study.py",
    }, indent=1))
    log(f"wrote {out.relative_to(REPO_ROOT)} in {metrics['seconds']} s")


if __name__ == "__main__":
    main()
