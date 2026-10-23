"""Hybrid, permission- and time-filtered retrieval.

Candidates come from PostgreSQL full-text search (lexical; not BM25) over `chunks` and exact pgvector
cosine search over `chunk_vectors` (kept apart since migration 0010 so neither scan reads the other's bytes). Both candidate queries apply tenant (RLS), role ACL, knowledge cutoff and
(in `effective` mode) effective-date filters in SQL. Results are fused with reciprocal
rank fusion and re-ordered by a deterministic rule-based reranker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from sqlalchemy import text

from .. import telemetry
from ..config import settings
from ..db import tenant_session
from .embed import embed, to_pgvector
from .rerank import Reranker, load_reranker, rerank_results

RRF_K = 60
# Answer support (Phase 5, P2-KNOW-01). The best passage is offered as an answer only when it covers enough of the
# question's content terms (stemmed, stopwords removed) or is close in embedding space while every content term occurs in
# some retrieved candidate; otherwise the search abstains and lists passages as related only. An unscoped question
# (no product identifier, no supplier filter) whose best passages come from different suppliers with nearly equal scores is
# ambiguous. Thresholds were fitted on the development half of study R3 and reported on its test half
# (evaluations/answer_support_study.py); change them only through that study. Measured limit (R3): these retrieval-only
# signals cannot tell an out-of-scope question from a reworded in-scope one, so abstention on out-of-scope questions is
# partial and some reworded questions are listed as related passages instead of answered (PHASE-05).
SUPPORT_MIN_COVERAGE = 0.40
SUPPORT_MIN_SIMILARITY = 0.50
AMBIGUITY_MARGIN = 0.05

BASE_FILTER = """
  dv.known_at <= :as_of
  AND :role = ANY(d.allowed_roles)
  AND (:mode = 'known' OR (dv.valid_from <= :eff AND (dv.valid_to IS NULL OR dv.valid_to >= :eff)))
  AND (CAST(:supplier AS text) IS NULL OR d.supplier_id = :supplier)
  AND (CAST(:doc AS uuid) IS NULL OR d.id = CAST(:doc AS uuid))
"""

# The query vector must be parsed ONCE per statement. As a bare CAST(:qv AS vector) it is constant-folded only while
# PostgreSQL uses a custom plan; once the driver's prepared statement switches to a generic plan the cast ran once per
# scanned row (100,000 text->vector parses, 5.5 s instead of 0.4 s at the ARC-07 reference size). The scalar subquery is an
# InitPlan in both plan kinds.
QV = "(SELECT CAST(:qv AS vector))"

SELECT_COLS = """c.id, c.version_id, c.section, c.body, c.char_start, c.char_end, d.id AS document_id,
  d.title, d.doc_type, d.supplier_id, d.source_kind, dv.version_label, dv.valid_from, dv.valid_to,
  dv.known_at, dv.supersedes_version_id, dv.sha256, tsvector_to_array(c.tsv) AS lexemes"""


@dataclass
class Evidence:
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    version_label: str
    section: str
    excerpt: str
    char_start: int
    char_end: int
    valid_from: date
    valid_to: date | None
    known_at: datetime
    supplier_id: str | None
    source_kind: str
    sha256: str
    supersedes_version_id: str | None
    score: float
    signals: dict = field(default_factory=dict)


def _row_to_evidence(r, score, signals) -> Evidence:
    return Evidence(str(r.id), str(r.document_id), str(r.version_id), r.title, r.version_label, r.section,
                    r.body, r.char_start, r.char_end, r.valid_from, r.valid_to, r.known_at, r.supplier_id,
                    r.source_kind, r.sha256, str(r.supersedes_version_id) if r.supersedes_version_id else None,
                    score, signals)


def answer_support(query_lexemes: set[str], results: list[Evidence], lexemes: dict[str, set[str]], *,
                   entities: list[str], scoped: bool, min_coverage: float = None, min_similarity: float = None,
                   ambiguity_margin: float = None) -> dict:
    """Whether the best passage supports an answer, and whether an unscoped question is ambiguous (see the constants)."""
    min_coverage = SUPPORT_MIN_COVERAGE if min_coverage is None else min_coverage
    min_similarity = SUPPORT_MIN_SIMILARITY if min_similarity is None else min_similarity
    ambiguity_margin = AMBIGUITY_MARGIN if ambiguity_margin is None else ambiguity_margin
    if not results:
        return {"supported": False, "reason": "no permitted passage", "coverage": 0.0, "ambiguous": False}
    top = results[0]
    seen = set().union(*lexemes.values()) if lexemes else set()
    unsupported = sorted(query_lexemes - seen)
    coverage = len(query_lexemes & lexemes.get(top.chunk_id, set())) / len(query_lexemes) if query_lexemes else 0.0
    sim = top.signals.get("vector_similarity")
    by_coverage = coverage >= min_coverage
    by_similarity = sim is not None and sim >= min_similarity and not unsupported
    supported = by_coverage or by_similarity
    rival = next((ev for ev in results[1:] if ev.supplier_id and ev.supplier_id != top.supplier_id), None)
    ambiguous = bool(supported and not entities and not scoped and rival is not None and top.supplier_id
                     and (top.score - rival.score) <= ambiguity_margin * top.score)
    reason = ("answer supported by term coverage" if by_coverage else "answer supported by semantic similarity"
              if by_similarity else "the passages do not cover the question" + (f" (no passage mentions: {', '.join(unsupported)})"
                                                                                 if unsupported else ""))
    return {"supported": supported, "ambiguous": ambiguous, "reason": reason, "coverage": round(coverage, 3),
            "top_similarity": sim, "unsupported_terms": unsupported,
            "candidate_suppliers": sorted({ev.supplier_id for ev in results if ev.supplier_id})[:8] if ambiguous else []}


def search(tenant_id, query: str, *, as_of: datetime, role: str, effective_date: date | None = None,
           mode: Literal["effective", "known"] = "effective", supplier_id: str | None = None,
           entities: list[str] | None = None, k: int = 8, use_vectors: bool = True,
           channels: tuple[str, ...] = ("lexical", "vector"), rerank: bool = True, n_candidates: int = 30,
           document_id: str | None = None, reranker: Reranker | None = None, explain: bool = False) -> dict:
    """`channels` and `rerank` exist for controlled ablations (R1/R2); the product uses the defaults. `reranker` overrides
    the configured cross-encoder (tests, studies); with none configured only the rule-based reranker runs."""
    with telemetry.span("retrieval.search", **{"tenant.id": str(tenant_id), "retrieval.role": role, "retrieval.k": k}):
        return _search(tenant_id, query, as_of=as_of, role=role, effective_date=effective_date, mode=mode,
                       supplier_id=supplier_id, entities=entities, k=k, use_vectors=use_vectors, channels=channels,
                       rerank=rerank, n_candidates=n_candidates, document_id=document_id, reranker=reranker,
                       explain=explain)


def _search(tenant_id, query, *, as_of, role, effective_date, mode, supplier_id, entities, k, use_vectors, channels,
            rerank, n_candidates, document_id, reranker=None, explain=False) -> dict:
    eff = effective_date or as_of.date()
    use_vectors = use_vectors and "vector" in channels
    params = {"as_of": as_of, "eff": eff, "mode": mode, "role": role, "supplier": supplier_id, "q": query, "doc": document_id,
              "n": n_candidates}
    vectors = embed([query]) if use_vectors else None
    with tenant_session(tenant_id) as s:
        if settings.retrieval_statement_timeout_ms:
            # Cancel a search that cannot finish in useful time (Phase 3): it frees the CPU for requests still in time.
            s.execute(text("SELECT set_config('statement_timeout', :v, true)"),
                      {"v": str(int(settings.retrieval_statement_timeout_ms))})
        lexical = [] if "lexical" not in channels else s.execute(text(f"""
            SELECT {SELECT_COLS}, ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS rank
            FROM chunks c JOIN document_versions dv ON dv.id = c.version_id JOIN documents d ON d.id = dv.document_id
            WHERE c.tsv @@ websearch_to_tsquery('english', :q) AND {BASE_FILTER}
            ORDER BY rank DESC, c.id LIMIT :n"""), params).all()
        if not lexical and "lexical" in channels:
            # websearch requires all terms; retry with any-term matching for recall.
            terms = " | ".join(w for w in "".join(ch if ch.isalnum() else " " for ch in query).split() if len(w) > 2)
            if terms:
                lexical = s.execute(text(f"""
                    SELECT {SELECT_COLS}, ts_rank_cd(c.tsv, to_tsquery('english', :tq)) AS rank
                    FROM chunks c JOIN document_versions dv ON dv.id = c.version_id
                    JOIN documents d ON d.id = dv.document_id
                    WHERE c.tsv @@ to_tsquery('english', :tq) AND {BASE_FILTER}
                    ORDER BY rank DESC, c.id LIMIT :n"""), {**params, "tq": terms}).all()
        semantic = []
        if vectors:
            # Rank on the narrow vector table (distance computed once per row), then read the full rows of the top n only.
            semantic = s.execute(text(f"""
                WITH top AS (
                  SELECT v.chunk_id, v.embedding <=> {QV} AS dist
                  FROM chunk_vectors v JOIN document_versions dv ON dv.id = v.version_id
                  JOIN documents d ON d.id = dv.document_id
                  WHERE {BASE_FILTER}
                  ORDER BY dist, v.chunk_id LIMIT :n)
                SELECT {SELECT_COLS}, 1 - top.dist AS rank
                FROM top JOIN chunks c ON c.id = top.chunk_id JOIN document_versions dv ON dv.id = c.version_id
                JOIN documents d ON d.id = dv.document_id
                ORDER BY top.dist, c.id"""),
                {**params, "qv": to_pgvector(vectors[0])}).all()
        query_lexemes = set(s.execute(text("SELECT tsvector_to_array(to_tsvector('english', :q))"), {"q": query}).scalar() or [])
    fused: dict[str, dict] = {}
    for name, rows in (("lexical", lexical), ("vector", semantic)):
        for rank, r in enumerate(rows, start=1):
            entry = fused.setdefault(str(r.id), {"row": r, "rrf": 0.0, "signals": {}})
            entry["rrf"] += 1.0 / (RRF_K + rank)
            entry["signals"][f"{name}_rank"] = rank
            if name == "vector":
                entry["signals"]["vector_similarity"] = round(float(r.rank), 4)
    ents = [e.lower() for e in (entities or [])]
    # A chunk is demoted only when a newer version of the same section is also in the results.
    superseded = {(str(e["row"].supersedes_version_id), e["row"].section)
                  for e in fused.values() if e["row"].supersedes_version_id}
    results = []
    for e in fused.values():
        r, sig = e["row"], e["signals"]
        bonus = 0.0
        hits = [x for x in ents if x in r.body.lower()]
        if hits and rerank:
            bonus += 0.01 * len(hits)
            sig["entity_matches"] = hits
        if rerank and (str(r.version_id), r.section) in superseded:
            bonus -= 0.02
            sig["superseded_in_results"] = True
        sig["rrf"] = round(e["rrf"], 6)
        results.append(_row_to_evidence(r, e["rrf"] + bonus, sig))
    results.sort(key=lambda ev: (-ev.score, ev.chunk_id))
    reranker = (reranker or load_reranker()) if rerank else None
    rerank_note = None
    if reranker is not None:
        results, rerank_note = rerank_results(query, results, reranker, settings.reranker_candidates)
    elif rerank and settings.reranker_model:
        rerank_note = f"reranker {settings.reranker_model} could not be loaded; rule-based order used"
    # Abstain when the question names identifiers (e.g. product codes) that no permitted result contains.
    abstain = bool(ents) and not any(any(x in ev.excerpt.lower() for x in ents) for ev in results[:k])
    lexemes = {cid: set(e["row"].lexemes or []) for cid, e in fused.items()}
    support = answer_support(query_lexemes, results[:k], lexemes, entities=ents, scoped=bool(supplier_id or document_id))
    extra = {"support_inputs": {"query_lexemes": query_lexemes, "lexemes": lexemes, "entities": ents,
                                "scoped": bool(supplier_id or document_id)}} if explain else {}
    return {**extra,
        "abstain": abstain,
        "support": support,
        "results": results[:k],
        "mode": "hybrid" if vectors else "lexical_only",
        "degraded": "; ".join(x for x in (None if vectors or not use_vectors else "embedding service unavailable; lexical only",
                                          rerank_note) if x) or None,
        "filters": {"as_of": as_of.isoformat(), "effective_date": eff.isoformat(), "mode": mode, "role": role,
                    "supplier_id": supplier_id},
        "reranker": (f"{reranker.name} over reciprocal-rank fusion; supersession forced last" if reranker is not None and rerank_note is None else
                     "rule-based (entity match, supersession demotion) over reciprocal-rank fusion"),
    }
