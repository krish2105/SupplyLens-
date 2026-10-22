"""CSV onboarding wizard, workspace creation and membership administration (audit S18)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..authz import Actor
from ..onboarding import csv_import as ci
from ..onboarding import service as onb
from .deps import actor, csrf_guard
from .ratelimit import limit
from .schemas import (
    ImportBatch,
    ImportBatchRow,
    ImportTemplates,
    MembershipChanged,
    WorkspaceCreated,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_guard)])


def _guard(fn):
    try:
        return fn()
    except onb.OnboardingError as e:
        raise HTTPException(e.http, {"code": e.code, "message": str(e)}) from e


@router.get("/onboarding/templates", response_model=ImportTemplates)
def templates(a: Actor = Depends(actor)):
    a.require("read")
    return {"schema_version": ci.SCHEMA_VERSION, "max_bytes": ci.MAX_BYTES, "max_rows": ci.MAX_ROWS,
            "templates": {k: [c.__dict__ for c in cols] for k, cols in ci.TEMPLATES.items()}}


@router.get("/onboarding/templates/{kind}.csv", response_class=PlainTextResponse)
def template_file(kind: str, a: Actor = Depends(actor)):
    a.require("read")
    if kind not in ci.TEMPLATES:
        raise HTTPException(404, {"code": "not_found", "message": "unknown template"})
    return PlainTextResponse(ci.template_csv(kind), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="supplylens-{kind}-template.csv"'})


@router.get("/onboarding/batches", response_model=list[ImportBatchRow])
def batches(a: Actor = Depends(actor)):
    return onb.list_batches(a)


@router.post("/onboarding/batches", response_model=ImportBatch, status_code=201)
async def upload(kind: str = Form(...), rights: str = Form(...), file: UploadFile = File(...),
                 a: Actor = Depends(limit("import_upload", 20))):
    data = await file.read(ci.MAX_BYTES + 1)
    return _guard(lambda: onb.upload(a, kind=kind, file_name=file.filename or "upload.csv", data=data, rights=rights))


@router.get("/onboarding/batches/{batch_id}", response_model=ImportBatch)
def batch(batch_id: uuid.UUID, a: Actor = Depends(actor)):
    return _guard(lambda: onb.get(a, batch_id))


class MappingIn(BaseModel):
    mapping: dict[str, str | None]


@router.post("/onboarding/batches/{batch_id}/validate", response_model=ImportBatch)
def validate(batch_id: uuid.UUID, body: MappingIn, a: Actor = Depends(limit("import_validate", 30))):
    return _guard(lambda: onb.validate_batch(a, batch_id, body.mapping))


@router.post("/onboarding/batches/{batch_id}/publish", response_model=ImportBatch)
def publish(batch_id: uuid.UUID, a: Actor = Depends(limit("import_publish", 10))):
    return _guard(lambda: onb.publish(a, batch_id))


class WorkspaceIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,40}$")
    name: str = Field(min_length=2, max_length=80)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    weekly_budget_minor: int = Field(ge=0, le=10_000_000_000)
    coverage_days: int = Field(default=21, ge=7, le=28)


@router.post("/onboarding/workspaces", response_model=WorkspaceCreated, status_code=201)
def create_workspace(body: WorkspaceIn, a: Actor = Depends(limit("workspace_create", 5))):
    return _guard(lambda: onb.create_workspace(a, slug=body.slug, name=body.name, currency=body.currency,
                                               weekly_budget_minor=body.weekly_budget_minor,
                                               coverage_days=body.coverage_days))


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str | None = Field(default=None, pattern="^(viewer|planner|approver|tenant_admin)$")


@router.post("/admin/members", response_model=MembershipChanged)
def set_member(body: MemberIn, a: Actor = Depends(limit("membership", 30))):
    """Add, change (role) or remove (role null) a locally managed membership in this workspace."""
    return _guard(lambda: onb.set_membership(a, email=body.email, role=body.role))
