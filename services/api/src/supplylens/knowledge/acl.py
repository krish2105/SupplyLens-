"""Document access control applied on every path, direct or indirect (audit S10).

A document's `allowed_roles` decides who may read its text and anything derived from it: clause labels, chunk excerpts,
citations stored in agent runs and action evidence, and the title/section/version label disclosed next to a structured
term. Structured commercial values themselves (price, MOQ, multiple, lead time) are operational data and stay visible to
every reader of the workspace (DECISIONS D-044); only their link back to a restricted document is withheld.

Direct reads use `require_version`. Responses that carry stored evidence are passed through `redact`, which walks the
JSON, finds every object that references a document version (or a chunk), and strips the document-derived fields when
the reader's role may not see that document.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

WITHHELD = "withheld: this document is restricted for your role"
DERIVED_FIELDS = ("body", "excerpt", "text", "title", "section", "version_label", "char_start", "char_end", "sha256",
                  "file_name")


def require_version(s, role: str, version_id) -> dict | None:
    """The version row if `role` may read it, else None (callers answer 404 so existence is not disclosed)."""
    row = s.execute(text("""SELECT dv.*, d.title, d.supplier_id, d.source_kind, d.allowed_roles FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id WHERE dv.id = :i"""), {"i": version_id}).mappings().first()
    if not row or role not in row["allowed_roles"]:
        return None
    return dict(row)


def _walk(obj: Any, visit) -> None:
    if isinstance(obj, dict):
        visit(obj)
        for v in obj.values():
            _walk(v, visit)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, visit)


def _as_uuid(v) -> str | None:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError):
        return None


def redact(s, role: str, obj: Any) -> Any:
    """Strip document-derived fields the reader may not see. Mutates and returns `obj`."""
    versions, chunks = set(), set()

    def collect(d: dict) -> None:
        if (v := _as_uuid(d.get("document_version_id"))):
            versions.add(v)
        if (c := _as_uuid(d.get("chunk_id"))):
            chunks.add(c)
    _walk(obj, collect)
    if not versions and not chunks:
        return obj
    allowed_v = {str(r[0]) for r in s.execute(text("""SELECT dv.id FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id WHERE dv.id = ANY(CAST(:v AS uuid[])) AND :r = ANY(d.allowed_roles)"""),
        {"v": list(versions), "r": role})}
    allowed_c = {str(r[0]) for r in s.execute(text("""SELECT c.id FROM chunks c JOIN document_versions dv ON dv.id = c.version_id
        JOIN documents d ON d.id = dv.document_id WHERE c.id = ANY(CAST(:c AS uuid[])) AND :r = ANY(d.allowed_roles)"""),
        {"c": list(chunks), "r": role})}

    def strip(d: dict) -> None:
        v, c = _as_uuid(d.get("document_version_id")), _as_uuid(d.get("chunk_id"))
        if (v and v not in allowed_v) or (c and c not in allowed_c):
            for f in DERIVED_FIELDS:
                if f in d:
                    d[f] = None
            d["withheld"] = WITHHELD
    _walk(obj, strip)
    return obj
