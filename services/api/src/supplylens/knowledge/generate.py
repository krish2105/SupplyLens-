"""Cited generative answers over supplier documents (F1).

Reverses D-041 for local use only (D-094): a local model (Ollama) may phrase an answer, but only from the passages the
retriever returned and only after the extractive layer agreed there is something to answer. Every sentence must cite at
least one numbered passage, every cited number must exist, and every figure in a sentence (prices, quantities, days)
must appear in a passage it cites. An answer that fails any check is withheld and the reason is shown; the passages
remain the evidence. The public demo never generates (no model there, and the lockdown keeps it off).
"""
from __future__ import annotations

import json
import re
import time

import httpx

from ..config import settings
from .retrieve import Evidence

SYSTEM = (
    "You answer questions about supplier agreements for an operations planner. Use ONLY the numbered passages you are "
    "given; never use outside knowledge. Write at most four short sentences. Every sentence must end with the numbers of "
    "the passages that support it. Copy figures (prices, quantities, days, dates) exactly as the passages write them. "
    'Reply with JSON only: {"answer": [{"sentence": "...", "cites": [1]}], "insufficient": false}. If the passages do '
    'not answer the question, reply {"answer": [], "insufficient": true}.'
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
MAX_PASSAGES, MAX_SENTENCES = 5, 4


def _norm(n: str) -> str:
    return n.replace(",", "")


def numbers_in(text: str) -> set[str]:
    return {_norm(n) for n in NUMBER.findall(text)}


def check(answer: dict, passages: list[Evidence]) -> tuple[list[dict], str | None]:
    """Validate a parsed model reply. Returns (sentences with their passage indexes, reason it fails or None)."""
    if not isinstance(answer, dict) or not isinstance(answer.get("answer"), list):
        return [], "the model reply was not in the required form"
    if answer.get("insufficient") or not answer["answer"]:
        return [], "the model found that the passages do not answer the question"
    out = []
    for item in answer["answer"][:MAX_SENTENCES + 1]:
        sentence = str(item.get("sentence", "")).strip() if isinstance(item, dict) else ""
        cites = item.get("cites") if isinstance(item, dict) else None
        if not sentence:
            return [], "an empty sentence"
        if not isinstance(cites, list) or not cites or not all(isinstance(c, int) and 1 <= c <= len(passages) for c in cites):
            return [], f"a sentence without a valid citation: {sentence[:80]!r}"
        cited_numbers = set().union(*(numbers_in(passages[c - 1].excerpt) for c in cites))
        missing = sorted(numbers_in(sentence) - cited_numbers)
        if missing:
            return [], f"figures not in the cited passages ({', '.join(missing)}): {sentence[:80]!r}"
        out.append({"sentence": sentence, "cites": sorted(set(cites))})
    if len(out) > MAX_SENTENCES:
        return [], "the answer was longer than allowed"
    return out, None


def _chat(url: str, body: dict, timeout: float) -> dict:
    """One call to the local model (the only network call here; tests replace it)."""
    r = httpx.post(f"{url}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def citation(e: Evidence, n: int) -> dict:
    return {"n": n, "chunk_id": e.chunk_id, "document_id": e.document_id, "version_id": e.version_id, "version_label": e.version_label,
            "title": e.title, "section": e.section, "char_start": e.char_start, "char_end": e.char_end}


def generate(question: str, passages: list[Evidence], *, model: str | None = None, url: str | None = None,
             timeout: float | None = None) -> dict:
    """Ask the local model; return a checked answer or a withheld one with the reason. Never raises for model errors."""
    model, url = model or settings.generation_model, url or settings.ollama_url
    passages = passages[:MAX_PASSAGES]
    numbered = "\n\n".join(f"[{i}] {p.title} {p.version_label}, {p.section}:\n{p.excerpt}" for i, p in enumerate(passages, 1))
    body = {"model": model, "stream": False, "format": "json",
            "options": {"temperature": 0, "seed": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Passages:\n\n{numbered}\n\nQuestion: {question}"}]}
    base = {"type": "generated", "model": model, "citations": [citation(p, i) for i, p in enumerate(passages, 1)]}
    t0 = time.time()
    try:
        reply = json.loads(_chat(url, body, timeout or settings.generation_timeout_s)["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {**base, "abstained": True, "sentences": [], "latency_ms": round((time.time() - t0) * 1000),
                "reason": f"the local model is unavailable or replied in an unreadable form ({type(e).__name__})"}
    sentences, reason = check(reply, passages)
    return {**base, "abstained": reason is not None, "sentences": sentences if reason is None else [], "reason": reason,
            "latency_ms": round((time.time() - t0) * 1000)}
