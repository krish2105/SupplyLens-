"""Build the human-review sheet for the R2 time-aware retrieval questions.

    uv run python evaluations/r2_review_pack.py                # sample sheet from the frozen task file (no database)
    uv run python evaluations/r2_review_pack.py --with-evidence # also pull the expected passage text (needs the UCI workspace)

R2's 118 questions were generated from the same simulated records that produced the agreements, so a pass proves the
temporal mechanism, not that a person agrees the question and its expected passage are right. ARC-04 asks for a frozen,
independently checked set. This script draws a reproducible stratified sample for a reviewer: every rare case type in
full, plus a random slice of the common ones. The reviewer columns are left empty; only a person can fill them.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "evaluations" / "tasksets" / "r2_supplier_terms_v1.jsonl"
OUT = REPO / "evaluations" / "tasksets" / "r2_review_sample.csv"
SEED = 20261021
SAMPLE = {"current": 20}          # case types not listed are taken in full (they are rare: 4-10 questions each)

REVIEW_COLUMNS = [
    "reviewer", "review_date",
    "question_is_clear (yes/no)",           # would a buyer ask this and understand it?
    "expected_passage_is_correct (yes/no)", # does the expected version+section answer the question as of the stated dates?
    "dates_make_sense (yes/no)",            # effective date and knowledge cutoff consistent with the case type
    "better_passage_exists (yes/no)",       # a different permitted passage answers it better
    "notes",
]


def load() -> list[dict]:
    return [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]


def sample(rows: list[dict]) -> list[dict]:
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    rng = random.Random(SEED)
    out = []
    for case, rs in sorted(by_case.items()):
        rs = sorted(rs, key=lambda r: r["id"])
        out += rng.sample(rs, SAMPLE[case]) if case in SAMPLE and SAMPLE[case] < len(rs) else rs
    return out


def evidence_text(rows: list[dict]) -> dict[str, str]:
    from sqlalchemy import text

    from supplylens.db import tenant_session
    from supplylens.seed import tenant_id
    out = {}
    with tenant_session(tenant_id("uci-research")) as s:
        for r in rows:
            if not r.get("expect_version_id"):
                continue
            body = s.execute(text("SELECT body FROM chunks WHERE version_id = CAST(:v AS uuid) AND section = :s ORDER BY ordinal LIMIT 1"),
                             {"v": r["expect_version_id"], "s": r["expect_section"]}).scalar()
            out[r["id"]] = (body or "")[:600]
    return out


def main() -> None:
    rows = sample(load())
    texts = evidence_text(rows) if "--with-evidence" in sys.argv else {}
    cols = ["id", "case", "query", "supplier_id", "effective_date", "knowledge_cutoff", "expect_term_id", "expect_version_id",
            "expect_section", "expected_passage_text"] + REVIEW_COLUMNS
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["id"], r["case"], r["query"], r["supplier_id"], r["effective_date"], r["knowledge_cutoff"],
                        r.get("expect_term_id") or "", r.get("expect_version_id") or "(none: system should abstain)",
                        r.get("expect_section") or "", texts.get(r["id"], "")] + [""] * len(REVIEW_COLUMNS))
    counts = defaultdict(int)
    for r in rows:
        counts[r["case"]] += 1
    print(f"{len(rows)} of {len(load())} questions -> {OUT.relative_to(REPO)}  {dict(counts)}")


if __name__ == "__main__":
    main()
