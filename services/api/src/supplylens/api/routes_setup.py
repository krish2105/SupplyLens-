"""Token-guarded hosted setup (supplylens/hosting/setup.py). Absent unless SUPPLYLENS_SETUP_TOKEN is set."""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Header, HTTPException

from ..hosting import setup

router = APIRouter(prefix="/api/v1/internal")


@router.post("/setup/{step}", include_in_schema=False)
def run_setup(step: str, x_setup_token: str | None = Header(None)):
    token = os.environ.get("SUPPLYLENS_SETUP_TOKEN", "")
    if len(token) < 32 or not x_setup_token or not secrets.compare_digest(token, x_setup_token):
        raise HTTPException(404, {"code": "not_found", "message": "Not Found"})
    if step not in ("schema", "data"):
        raise HTTPException(404, {"code": "not_found", "message": "Not Found"})
    return setup.schema() if step == "schema" else setup.data()
