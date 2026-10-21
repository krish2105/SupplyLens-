"""Local embedding adapter (Ollama). Returns None when unavailable so callers fall back
to lexical retrieval and report the degraded mode instead of failing silently."""
from __future__ import annotations

import httpx

from ..config import settings


def embed(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    if not texts:
        return []
    try:
        r = httpx.post(f"{settings.ollama_url}/api/embed",
                       json={"model": settings.embed_model, "input": texts}, timeout=timeout)
        r.raise_for_status()
        vectors = r.json()["embeddings"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    if len(vectors) != len(texts) or any(len(v) != settings.embed_dim for v in vectors):
        return None
    return vectors


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"
