"""Hand-off ("talk to a person"): a support ticket in the shape of HubSpot's CRM tickets API, dry run unless enabled.

HubSpot facts used here (read 2026-11-10; re-check before enabling):
  * Create a ticket: POST https://api.hubapi.com/crm/objects/2026-09/tickets. HubSpot replaced numeric paths (/crm/v3/)
    with date-versioned ones (2026-03, then 2026-09, the version the "latest" reference shows); a version keeps working
    until its end-of-life date. Success is 201 with the new object's `id`.
    https://developers.hubspot.com/docs/api-reference/latest/crm/objects/tickets/create-ticket
    https://developers.hubspot.com/docs/api-reference/latest/crm/objects/tickets/guide
    https://developers.hubspot.com/docs/api-reference/latest/overview
  * Body: {"properties": {...}, "associations": [...]}. `subject` and `hs_pipeline_stage` are required; `hs_pipeline`
    falls back to the default pipeline when omitted; both take internal ids (the guide's examples use pipeline "0" and
    stage "1"); `hs_ticket_priority` takes LOW / MEDIUM / HIGH; `content` is the ticket description.
  * Auth: a bearer token in the Authorization header, from a service key (Development > Keys > Service keys) or an app's
    access token, with the scope crm.objects.tickets.write (the legacy `tickets` scope is to be migrated).
    https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/account-service-keys
    https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes
  * Legacy private apps can no longer be created (from 26 Oct 2026; 28 Sep 2026 for newer accounts); existing ones work.
    https://developers.hubspot.com/changelog/legacy-private-app-creation-sunset

Modes. Default, and always in the public demo profile: a dry run that builds the payload, records it in the audit log
(the owner chose "stub: record the payload locally", WP6) and returns it with sent=false. A real call happens only when
SUPPLYLENS_HUBSPOT_ENABLED=true AND HUBSPOT_ACCESS_TOKEN is set in the process environment (not read from .env, so a
stray file line cannot switch it on) AND the profile is not demo. One attempt with a timeout: a refusal (4xx) is never
retried, nor is a timeout (the ticket may exist). The token is never logged, stored or returned.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from ..authz import Actor
from ..config import settings
from ..db import control_session, tenant_session

log = logging.getLogger("supplylens.assistant")

API_BASE = "https://api.hubapi.com"
API_VERSION = "2026-09"
TICKETS_PATH = f"/crm/objects/{API_VERSION}/tickets"
TIMEOUT_S = 10.0
DRY_RUN_MESSAGE = "Dry run: ticket not sent — HubSpot is not connected."
STATUS_PRIORITY = {"withheld": "MEDIUM", "error": "MEDIUM", "choose": "LOW", "answered": "LOW", "not_asked": "LOW"}


def mode() -> tuple[bool, str]:
    """(send for real?, why not). Read on every call: switching it on or off needs no restart."""
    if settings.environment == "demo":
        return False, "the public demo never sends tickets"
    if os.environ.get("SUPPLYLENS_HUBSPOT_ENABLED", "").strip().lower() != "true":
        return False, "SUPPLYLENS_HUBSPOT_ENABLED is not true"
    if not os.environ.get("HUBSPOT_ACCESS_TOKEN", "").strip():
        return False, "no HubSpot access token is configured"
    return True, ""


def build_payload(a: Actor, workspace: str, question: str, answer_status: str, note: str | None) -> dict:
    lines = [f"Question asked in SupplyLens (workspace {workspace}): {question}",
             f"Assistant result: {answer_status}",
             f"Requested by: {a.email} (role {a.role})"]
    if note:
        lines.append(f"Note from the user: {note}")
    lines.append("Created by the SupplyLens status assistant; the assistant only reads records and changed nothing.")
    return {
        "properties": {
            "subject": f"SupplyLens: {question[:80]}{'…' if len(question) > 80 else ''}",
            "content": "\n".join(lines),
            "hs_pipeline": os.environ.get("SUPPLYLENS_HUBSPOT_PIPELINE", "0"),
            "hs_pipeline_stage": os.environ.get("SUPPLYLENS_HUBSPOT_PIPELINE_STAGE", "1"),
            "hs_ticket_priority": STATUS_PRIORITY.get(answer_status, "LOW"),
        },
        "associations": [],
    }


def _post(url: str, payload: dict, token: str) -> httpx.Response:
    """The only outbound call. Separate so tests replace it; no retry here or anywhere above it."""
    return httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      timeout=TIMEOUT_S)


def _audit(a: Actor, action: str, entity_id: str, detail: dict) -> None:
    with tenant_session(a.tenant_id) as s:
        s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) "
                       "VALUES (:t, :a, :ac, 'support_ticket', :e, CAST(:d AS jsonb))"),
                  {"t": a.tenant_id, "a": a.user_id, "ac": action, "e": entity_id, "d": json.dumps(detail, default=str)})


def hand_off(a: Actor, question: str, answer_status: str, note: str | None) -> dict:
    a.require("read")
    with control_session() as s:
        workspace = s.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": a.tenant_id}).scalar() or str(a.tenant_id)
    payload = build_payload(a, workspace, question, answer_status, note)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    endpoint = f"POST {API_BASE}{TICKETS_PATH}"
    real, why = mode()
    if not real:
        _audit(a, "assistant.handoff_dry_run", f"dry-run:{digest[:16]}",
               {"mode": "dry_run", "sent": False, "reason": why, "endpoint": endpoint, "payload": payload})
        return {"mode": "dry_run", "sent": False, "ticket_id": None, "payload": payload, "endpoint": endpoint,
                "message": DRY_RUN_MESSAGE, "reason": why}

    token = os.environ["HUBSPOT_ACCESS_TOKEN"].strip()
    failure = None
    try:
        r = _post(API_BASE + TICKETS_PATH, payload, token)
    except httpx.TimeoutException:
        failure = (504, "hubspot_timeout", f"HubSpot did not answer within {TIMEOUT_S:.0f} s. The ticket may or may not exist; "
                                           "nothing was retried. Check HubSpot before asking again.")
    except httpx.HTTPError as e:
        failure = (502, "hubspot_unreachable", f"HubSpot could not be reached ({type(e).__name__}); no ticket was created.")
    else:
        if 400 <= r.status_code < 500:
            failure = (502, "hubspot_rejected", f"HubSpot refused the ticket (HTTP {r.status_code}); not retried. Check the "
                                                "access token, its crm.objects.tickets.write scope and the pipeline ids.")
        elif r.status_code >= 300:
            failure = (502, "hubspot_error", f"HubSpot answered HTTP {r.status_code}; no retry was made.")
    if failure is None:
        try:
            ticket_id = str(r.json()["id"])
        except (ValueError, KeyError, TypeError):
            failure = (502, "hubspot_unreadable", "HubSpot accepted the request but its reply had no ticket id.")
    if failure is not None:
        status, code, message = failure
        log.warning("HubSpot ticket hand-off failed: %s", code)          # never the token or the request headers
        _audit(a, "assistant.handoff_failed", f"failed:{digest[:16]}",
               {"mode": "hubspot", "sent": False, "code": code, "endpoint": endpoint, "payload": payload})
        raise HTTPException(status, {"code": code, "message": message})
    _audit(a, "assistant.handoff_sent", ticket_id, {"mode": "hubspot", "sent": True, "endpoint": endpoint,
                                                    "ticket_id": ticket_id, "payload": payload})
    return {"mode": "hubspot", "sent": True, "ticket_id": ticket_id, "payload": payload, "endpoint": endpoint,
            "message": f"Ticket {ticket_id} created in HubSpot.", "reason": None}
