"""Cross-encoder reranking: it may only re-order what the filters admitted, supersession stays a hard rule, and every
failure falls back to the rule-based order with a note. Uses a stand-in scorer (real weights are not available here)."""
from dataclasses import dataclass, field

import pytest

from supplylens.knowledge import rerank
from supplylens.knowledge.rerank import load_reranker, rerank_results


@dataclass
class Ev:
    chunk_id: str
    excerpt: str
    score: float
    signals: dict = field(default_factory=dict)


class ByLength:
    name = "stub:by-length"

    def score(self, query, passages):
        return [float(len(p)) / 10.0 - 3.0 for p in passages]


class Boom:
    name = "stub:boom"

    def score(self, query, passages):
        raise RuntimeError("model crashed")


class WrongCount:
    name = "stub:wrong-count"

    def score(self, query, passages):
        return [0.0]


def _results():
    return [Ev("a", "short", 0.30), Ev("b", "a much longer passage about lead time", 0.20),
            Ev("c", "medium length text", 0.10), Ev("z", "tail item beyond the candidate window", 0.05)]


def test_reorders_the_candidate_head_and_leaves_the_tail():
    out, note = rerank_results("q", _results(), ByLength(), top_n=3)
    assert note is None
    assert [r.chunk_id for r in out] == ["b", "c", "a", "z"]
    assert all("cross_encoder" in r.signals for r in out[:3]) and "cross_encoder" not in out[3].signals


def test_superseded_passages_are_forced_behind_all_others():
    res = _results()
    res[1].signals["superseded_in_results"] = True            # the best-scoring one for the stub, but superseded
    out, _ = rerank_results("q", res, ByLength(), top_n=3)
    assert [r.chunk_id for r in out][:3] == ["c", "a", "b"]


@pytest.mark.parametrize("bad", [Boom(), WrongCount()])
def test_failures_fall_back_to_the_original_order_and_say_so(bad):
    res = _results()
    out, note = rerank_results("q", res, bad, top_n=3)
    assert [r.chunk_id for r in out] == ["a", "b", "c", "z"]
    assert note and "rule-based order used" in note


def test_single_candidate_is_not_scored():
    class Never:
        name = "never"

        def score(self, *a):
            raise AssertionError("should not be called")

    out, note = rerank_results("q", _results()[:1], Never(), top_n=3)
    assert note is None and len(out) == 1


def test_entity_matches_are_kept_as_a_small_bonus():
    res = [Ev("a", "x" * 50, 0.3, {"entity_matches": ["20724"]}), Ev("b", "x" * 50, 0.2)]
    out, _ = rerank_results("q", res, ByLength(), top_n=2)
    assert out[0].chunk_id == "a"


def test_unconfigured_or_unloadable_reranker_is_none(monkeypatch):
    monkeypatch.setattr(rerank.settings, "reranker_model", None)
    assert load_reranker() is None
    monkeypatch.setattr(rerank.settings, "reranker_model", "/nonexistent/model-dir")
    rerank._cache.clear()
    assert load_reranker() is None                            # sentence-transformers / weights absent: degrade, do not raise
    rerank._cache.clear()
