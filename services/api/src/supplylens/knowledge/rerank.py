"""Optional cross-encoder reranking of retrieval candidates.

A cross-encoder reads the query and one passage together and returns a relevance score; it is slower than the vector and
lexical channels (one model pass per candidate) so it only re-orders the top `reranker_candidates` after fusion.

It is OFF unless `SUPPLYLENS_RERANKER_MODEL` names a model directory or id that the host can load, and it can only ever
change the ORDER of candidates the SQL filters already admitted: tenant, role ACL, knowledge cutoff and effective-date
filtering all happen before it, so it cannot surface a document the caller may not see or one that was not yet known.

Supersession stays a hard rule: a passage whose newer version is also in the results is placed after every passage that
is not superseded, whatever the cross-encoder thinks. If the model cannot be loaded or raises, the rule-based order stands
and the response says so (`degraded`). This is the same fail-open-to-simple pattern as the embedding service.

Status: wired and tested with a stand-in scorer. It has NOT been run with real cross-encoder weights in this build
(they are downloaded from a model hub the build environment cannot reach), so its effect on recall is unmeasured.
`evaluations/retrieval_study.py R2 --reranker` runs the comparison once weights are present.
"""
from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from typing import Protocol

from ..config import settings

log = logging.getLogger("supplylens.rerank")


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    """sentence-transformers CrossEncoder on CPU. Install with `uv pip install sentence-transformers` (not in the lock)."""

    def __init__(self, model: str, max_length: int = 512):
        from sentence_transformers import CrossEncoder  # lazy: heavy import, optional dependency

        self.name = f"cross-encoder:{model}"
        self._model = CrossEncoder(model, max_length=max_length, device="cpu")

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [float(x) for x in self._model.predict([(query, p) for p in passages], show_progress_bar=False)]


_lock = threading.Lock()
_cache: dict[str, Reranker | None] = {}


def load_reranker() -> Reranker | None:
    """The configured reranker, loaded once per process; None when not configured or not loadable."""
    model = settings.reranker_model
    if not model:
        return None
    with _lock:
        if model not in _cache:
            try:
                _cache[model] = CrossEncoderReranker(model)
            except Exception as e:     # missing package, missing weights, bad path: degrade, do not fail the request
                log.warning("reranker %s unavailable: %s", model, e)
                _cache[model] = None
        return _cache[model]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 50.0), -50.0)))


def rerank_results(query: str, results: list, reranker: Reranker, top_n: int) -> tuple[list, str | None]:
    """Re-order the first `top_n` results (already fused, rule-scored and sorted). Returns (results, degraded note).

    Results need `.excerpt`, `.score` and a `.signals` dict. Entity-match bonuses already inside `.score` are kept as a
    small additive term; superseded passages are forced behind all others."""
    head, tail = results[:top_n], results[top_n:]
    if len(head) < 2:
        return results, None
    try:
        raw = reranker.score(query, [r.excerpt for r in head])
    except Exception as e:
        log.warning("reranker %s failed: %s", reranker.name, e)
        return results, f"reranker {reranker.name} failed; rule-based order used"
    if len(raw) != len(head):
        return results, f"reranker {reranker.name} returned {len(raw)} scores for {len(head)} passages; rule-based order used"
    for r, s in zip(head, raw, strict=True):
        hits = len(r.signals.get("entity_matches", []))
        r.signals["cross_encoder"] = round(s, 4)
        r.score = _sigmoid(s) + 0.01 * hits
    head.sort(key=lambda r: (bool(r.signals.get("superseded_in_results")), -r.score, r.chunk_id))
    return head + tail, None
