"""Document version ingestion: content-addressed storage, section chunking, embeddings.

Chunks keep character offsets into the stored original so every citation can be
highlighted exactly. Documents are data: nothing inside them is executed or obeyed.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text

from ..config import settings
from ..db import tenant_session
from .embed import embed, to_pgvector

PARSER_VERSION = "plaintext-sections-v1"


@dataclass
class Chunk:
    ordinal: int
    section: str
    start: int
    end: int
    body: str


def chunk_text(body: str) -> list[Chunk]:
    """Split on blank lines; a line ending with ':' or starting with '#'/'Section' names a section."""
    chunks, section, ordinal = [], "Preamble", 0
    for m in re.finditer(r"(?:[^\n]+\n?)+", body):
        block = m.group(0).strip()
        if not block:
            continue
        first = block.splitlines()[0].strip()
        if first.startswith("#") or re.match(r"^(Section|Clause|Schedule)\b", first, re.I):
            section = first.lstrip("# ").strip()
        chunks.append(Chunk(ordinal, section if ordinal else "Preamble", m.start(),
                            m.start() + len(m.group(0).rstrip()), block))
        ordinal += 1
    return chunks


def store_bytes(tenant_id, data: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    path = settings.storage_path / "documents" / str(tenant_id) / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return digest, str(path.relative_to(settings.storage_path))


def read_version_text(storage_key: str) -> str:
    return (settings.storage_path / storage_key).read_text(encoding="utf-8")


def ingest_document(tenant_id, *, title: str, doc_type: str, supplier_id: str | None, source_kind: str,
                    file_name: str, body: str, version_label: str, known_at: datetime, valid_from: date,
                    valid_to: date | None = None, supersedes_version_id=None, document_id=None,
                    allowed_roles: list[str] | None = None) -> dict:
    data = body.encode("utf-8")
    digest, key = store_bytes(tenant_id, data)
    chunks = chunk_text(body)
    vectors = embed([c.body for c in chunks])
    with tenant_session(tenant_id) as s:
        existing = s.execute(text("SELECT id, document_id FROM document_versions WHERE sha256=:h"),
                             {"h": digest}).first()
        if existing:
            return {"version_id": existing.id, "document_id": existing.document_id, "reused": True}
        if document_id is None:
            document_id = uuid.uuid4()
            s.execute(text(
                "INSERT INTO documents (id, tenant_id, title, doc_type, supplier_id, source_kind, allowed_roles) "
                "VALUES (:i,:t,:ti,:dt,:sup,:sk, COALESCE(:roles, ARRAY['viewer','planner','approver','tenant_admin']))"),
                {"i": document_id, "t": tenant_id, "ti": title, "dt": doc_type, "sup": supplier_id,
                 "sk": source_kind, "roles": allowed_roles})
        vid = uuid.uuid4()
        s.execute(text(
            "INSERT INTO document_versions (id, tenant_id, document_id, version_label, file_name, sha256, "
            "storage_key, known_at, valid_from, valid_to, supersedes_version_id, parser_version, embed_model) "
            "VALUES (:i,:t,:d,:v,:f,:h,:k,:ka,:vf,:vt,:sv,:p,:em)"),
            {"i": vid, "t": tenant_id, "d": document_id, "v": version_label, "f": file_name, "h": digest,
             "k": key, "ka": known_at, "vf": valid_from, "vt": valid_to, "sv": supersedes_version_id,
             "p": PARSER_VERSION, "em": settings.embed_model if vectors else None})
        for c, v in zip(chunks, vectors or [None] * len(chunks), strict=True):
            cid = uuid.uuid4()
            s.execute(text(
                "INSERT INTO chunks (id, tenant_id, version_id, ordinal, section, char_start, char_end, body) "
                "VALUES (:i,:t,:v,:o,:s,:a,:b,:body)"),
                {"i": cid, "t": tenant_id, "v": vid, "o": c.ordinal, "s": c.section, "a": c.start, "b": c.end,
                 "body": c.body})
            if v:      # vectors live in their own table (migration 0010)
                s.execute(text("INSERT INTO chunk_vectors (chunk_id, tenant_id, version_id, embedding) VALUES (:i,:t,:v,CAST(:e AS vector))"),
                          {"i": cid, "t": tenant_id, "v": vid, "e": to_pgvector(v)})
    return {"version_id": vid, "document_id": document_id, "reused": False,
            "chunks": len(chunks), "embedded": vectors is not None}
