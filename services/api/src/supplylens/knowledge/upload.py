"""Add a supplier document or a new version of one from the product (Phase 4, journey "document ingestion").

Plain text only (.txt, .md; UTF-8, at most 1 MB): the parser keeps character offsets so every citation can be highlighted,
and nothing in a document is executed. Workspace administrators only ("admin.write"), so the public demo's lockdown applies.

The knowledge clock is the server's: a version is known from the moment it is uploaded, never from a date the user types,
so a replay before that moment cannot cite it. The user states when it is in force (valid_from / valid_to). A version that
supersedes another belongs to the same document and must not start before the version it replaces.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import text

from ..authz import Actor
from ..db import tenant_session
from .ingest import ingest_document

MAX_BYTES = 1_000_000
DOC_TYPES = ("contract", "amendment", "policy")
SUFFIXES = (".txt", ".md")


class UploadError(Exception):
    def __init__(self, code: str, message: str, http: int = 422):
        super().__init__(message)
        self.code, self.http = code, http


def upload_document(actor: Actor, *, file_name: str, data: bytes, title: str, doc_type: str, version_label: str,
                    valid_from: date, valid_to: date | None = None, supplier_id: str | None = None,
                    supersedes_version_id: uuid.UUID | None = None) -> dict:
    actor.require("admin.write")
    title, version_label = title.strip(), version_label.strip()
    supplier_id = (supplier_id or "").strip() or None
    if not file_name.lower().endswith(SUFFIXES):
        raise UploadError("unsupported_type", "upload a plain-text document (.txt or .md)")
    if not data:
        raise UploadError("empty_file", "the file is empty")
    if len(data) > MAX_BYTES:
        raise UploadError("file_too_large", f"documents are limited to {MAX_BYTES // 1000} KB of text", 413)
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UploadError("not_utf8", "the file is not UTF-8 text") from e
    if "\x00" in body:
        raise UploadError("binary_content", "the file contains binary data")
    if not body.strip():
        raise UploadError("empty_file", "the file has no text")
    if not 1 <= len(title) <= 300 or not 1 <= len(version_label) <= 50:
        raise UploadError("invalid_fields", "a title (1-300 characters) and a version label (1-50) are required")
    if doc_type not in DOC_TYPES:
        raise UploadError("invalid_fields", f"document type must be one of {', '.join(DOC_TYPES)}")
    if valid_to is not None and valid_to < valid_from:
        raise UploadError("invalid_dates", "the version cannot end before it starts")

    document_id = None
    with tenant_session(actor.tenant_id) as s:
        if supplier_id and not s.execute(text("SELECT 1 FROM suppliers WHERE supplier_id=:s"), {"s": supplier_id}).first():
            raise UploadError("unknown_supplier", f"no supplier {supplier_id} in this workspace")
        if supersedes_version_id is not None:
            prior = s.execute(text("""SELECT dv.document_id, dv.valid_from, d.supplier_id FROM document_versions dv
                JOIN documents d ON d.id = dv.document_id WHERE dv.id = :v"""), {"v": supersedes_version_id}).first()
            if prior is None:                      # unknown here (row-level security hides other workspaces' versions)
                raise UploadError("unknown_version", "the version to supersede does not exist in this workspace", 404)
            if valid_from < prior.valid_from:
                raise UploadError("invalid_dates", f"an amendment cannot take effect before the version it replaces ({prior.valid_from})")
            document_id, supplier_id = prior.document_id, prior.supplier_id
        exists = s.execute(text("SELECT id FROM document_versions WHERE sha256 = encode(sha256(:b), 'hex')"),
                           {"b": data}).first()
        if exists:
            raise UploadError("duplicate_document", "this exact text is already stored as a document version", 409)

    known_at = datetime.now(UTC)
    res = ingest_document(actor.tenant_id, title=title, doc_type=doc_type, supplier_id=supplier_id, source_kind="uploaded",
                          file_name=file_name[:200], body=body, version_label=version_label, known_at=known_at,
                          valid_from=valid_from, valid_to=valid_to, supersedes_version_id=supersedes_version_id,
                          document_id=document_id)
    with tenant_session(actor.tenant_id) as s:
        s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) "
                       "VALUES (:t,:a,'document.uploaded','document_version',:e,CAST(:d AS jsonb))"),
                  {"t": actor.tenant_id, "a": actor.user_id, "e": str(res["version_id"]),
                   "d": json.dumps({"title": title, "version_label": version_label, "file_name": file_name,
                                    "supersedes_version_id": str(supersedes_version_id) if supersedes_version_id else None,
                                    "chunks": res.get("chunks"), "embedded": res.get("embedded")})})
    return {"document_id": str(res["document_id"]), "version_id": str(res["version_id"]), "chunks": res.get("chunks", 0),
            "embedded": bool(res.get("embedded")), "known_at": known_at}
