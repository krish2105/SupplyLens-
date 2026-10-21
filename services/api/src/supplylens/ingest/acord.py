"""Ingest the ACORD clause corpus (CC BY 4.0) into the contract-research workspace.

One document version holds the corpus; each clause is one chunk whose `section` is the ACORD
corpus id, so retrieval runs through exactly the same SQL path as supplier policies.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from ..config import REPO_ROOT
from ..db import tenant_session
from ..knowledge.embed import embed, to_pgvector
from ..knowledge.ingest import PARSER_VERSION, store_bytes

ACORD_DIR = REPO_ROOT / "data/raw/core/acord/extracted/ACORD Dataset & ReadMe/ACORD Dataset & ReadMe (external)"


def load_corpus() -> list[dict]:
    return [json.loads(l) for l in (ACORD_DIR / "corpus.jsonl").read_text().splitlines() if l.strip()]


def ingest(tenant_id, batch: int = 48, log=print) -> dict:
    corpus = load_corpus()
    parts, offsets, pos = [], [], 0
    for c in corpus:
        body = c["text"].strip()
        offsets.append((c["_id"], pos, pos + len(body), body))
        parts.append(body)
        pos += len(body) + 2
    full = "\n\n".join(parts)
    digest, key = store_bytes(tenant_id, full.encode())
    with tenant_session(tenant_id) as s:
        if s.execute(text("SELECT 1 FROM document_versions WHERE sha256=:h"), {"h": digest}).first():
            return {"reused": True, "clauses": len(corpus)}
        doc_id, vid = uuid.uuid4(), uuid.uuid4()
        s.execute(text("INSERT INTO documents (id, tenant_id, title, doc_type, supplier_id, source_kind) VALUES "
                       "(:i,:t,'ACORD clause corpus (Atticus Project, CC BY 4.0)','benchmark_corpus',NULL,'public')"),
                  {"i": doc_id, "t": tenant_id})
        s.execute(text("""INSERT INTO document_versions (id, tenant_id, document_id, version_label, file_name, sha256,
            storage_key, known_at, valid_from, parser_version, embed_model) VALUES (:i,:t,:d,'v1','corpus.jsonl',:h,:k,
            :ka,'1900-01-01',:p,:em)"""), {"i": vid, "t": tenant_id, "d": doc_id, "h": digest, "k": key,
                                           "ka": datetime.now(UTC), "p": PARSER_VERSION + "+acord", "em": "bge-m3:567m"})
    embedded = 0
    for b in range(0, len(offsets), batch):
        chunk = offsets[b: b + batch]
        vecs = embed([c[3] for c in chunk], timeout=120) or [None] * len(chunk)
        embedded += sum(v is not None for v in vecs)
        with tenant_session(tenant_id) as s:
            for (cid, a, z, body), v in zip(chunk, vecs, strict=True):
                s.execute(text("""INSERT INTO chunks (id, tenant_id, version_id, ordinal, section, char_start, char_end, body,
                    embedding) VALUES (:i,:t,:v,:o,:s,:a,:z,:b,CAST(:e AS vector))"""),
                    {"i": uuid.uuid4(), "t": tenant_id, "v": vid, "o": b, "s": cid, "a": a, "z": z, "b": body,
                     "e": to_pgvector(v) if v else None})
        if b % (batch * 20) == 0:
            log(f"acord: {b + len(chunk)}/{len(offsets)} clauses")
    return {"reused": False, "clauses": len(corpus), "embedded": embedded, "sha256": digest}


if __name__ == "__main__":
    from ..seed import tenant_id
    print(ingest(tenant_id("contract-research")))
