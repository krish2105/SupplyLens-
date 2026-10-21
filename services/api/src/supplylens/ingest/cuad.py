"""Ingest CUAD v1 supply / distribution / manufacturing agreements (CC BY 4.0) with expert labels.

Real public commercial contracts filed with the SEC. They are not UCI supplier terms. Effective
dates are not parsed from the text, so versions carry valid_from 1900-01-01 and the UI says so.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from ..config import REPO_ROOT
from ..db import tenant_session
from ..knowledge.embed import embed, to_pgvector
from ..knowledge.ingest import PARSER_VERSION, store_bytes

CUAD = REPO_ROOT / "data/raw/core/cuad/extracted/data/CUADv1.json"
KEYWORDS = ("SUPPLY", "DISTRIBUT", "MANUFACTUR")
TARGET = 1400


def windows(body: str) -> list[tuple[int, int]]:
    """Paragraph-packed windows of about TARGET characters, with exact offsets into the original."""
    paras = [(m.start(), m.end()) for m in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", body)]
    out, cur = [], None
    for a, z in paras:
        if cur is None:
            cur = [a, z]
        elif z - cur[0] <= TARGET:
            cur[1] = z
        else:
            out.append(tuple(cur))
            cur = [a, z]
    if cur:
        out.append(tuple(cur))
    final = []
    for a, z in out:  # split oversized single paragraphs
        while z - a > TARGET * 2:
            final.append((a, a + TARGET))
            a += TARGET
        final.append((a, z))
    return final


def ingest(tenant_id, log=print) -> dict:
    data = json.loads(CUAD.read_text())["data"]
    picked = [d for d in data if any(k in d["title"].upper() for k in KEYWORDS)]
    docs = labels = chunks = 0
    for d in picked:
        para = d["paragraphs"][0]
        body = para["context"]
        digest, key = store_bytes(tenant_id, body.encode())
        with tenant_session(tenant_id) as s:
            if s.execute(text("SELECT 1 FROM document_versions WHERE sha256=:h"), {"h": digest}).first():
                continue
        spans = windows(body)
        vecs = []
        for b in range(0, len(spans), 32):
            vecs += embed([body[a:z] for a, z in spans[b:b + 32]], timeout=180) or [None] * len(spans[b:b + 32])
        doc_id, vid = uuid.uuid4(), uuid.uuid4()
        title = d["title"].strip()
        with tenant_session(tenant_id) as s:
            s.execute(text("INSERT INTO documents (id, tenant_id, title, doc_type, supplier_id, source_kind) VALUES "
                           "(:i,:t,:ti,'commercial_contract',NULL,'public')"), {"i": doc_id, "t": tenant_id, "ti": title[:300]})
            s.execute(text("""INSERT INTO document_versions (id, tenant_id, document_id, version_label, file_name, sha256,
                storage_key, known_at, valid_from, parser_version, embed_model) VALUES (:i,:t,:d,'as filed',:f,:h,:k,:ka,
                '1900-01-01',:p,:em)"""), {"i": vid, "t": tenant_id, "d": doc_id, "f": title[:200] + ".txt", "h": digest,
                                          "k": key, "ka": datetime.now(UTC), "p": PARSER_VERSION + "+cuad-windows",
                                          "em": "bge-m3:567m"})
            for n, ((a, z), v) in enumerate(zip(spans, vecs, strict=True)):
                s.execute(text("""INSERT INTO chunks (id, tenant_id, version_id, ordinal, section, char_start, char_end, body,
                    embedding) VALUES (:i,:t,:v,:o,:s,:a,:z,:b,CAST(:e AS vector))"""),
                    {"i": uuid.uuid4(), "t": tenant_id, "v": vid, "o": n, "s": f"Part {n + 1}", "a": a, "z": z,
                     "b": body[a:z], "e": to_pgvector(v) if v else None})
            for qa in para["qas"]:
                cat = qa["id"].split("__")[-1]
                for ans in qa["answers"]:
                    st = ans["answer_start"]
                    s.execute(text("""INSERT INTO clause_labels (tenant_id, version_id, category, char_start, char_end, text, source)
                        VALUES (:t,:v,:c,:a,:z,:x,'CUAD v1 expert annotation')"""),
                        {"t": tenant_id, "v": vid, "c": cat, "a": st, "z": st + len(ans["text"]), "x": ans["text"][:4000]})
                    labels += 1
        docs += 1
        chunks += len(spans)
        if docs % 10 == 0:
            log(f"cuad: {docs}/{len(picked)} contracts")
    return {"contracts": docs, "chunks": chunks, "labels": labels, "selected_of": len(data)}


if __name__ == "__main__":
    from ..seed import tenant_id
    print(ingest(tenant_id("contract-research")))
