"""Order and stock status assistant (Phase 8 WP6): read-only questions answered from records, and a hand-off to a person.

Both routes need a signed-in member of the workspace (any role may read), the anti-CSRF header like every POST, and are
rate-limited per user with the same database-backed limiter and rate as POST /evidence/answer (20 a minute). Nothing here
writes business data: /ask only reads; /handoff writes one audit event and, only where explicitly enabled outside the
public demo, creates a HubSpot ticket (assistant/handoff.py).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from ..assistant import answer, handoff
from ..authz import Actor
from .deps import csrf_guard
from .ratelimit import limit
from .schemas import AssistantAnswer, AssistantHandoff

router = APIRouter(prefix="/api/v1/assistant", dependencies=[Depends(csrf_guard)])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class HandoffIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer_status: Literal["answered", "withheld", "choose", "error", "not_asked"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/ask", response_model=AssistantAnswer)
def ask(body: AskIn, a: Actor = Depends(limit("assistant", 20))):
    """Answer from this workspace's records with a citation on every sentence, ask which product when several match, or
    withhold with the reason. Deterministic and extractive: no model is called, nothing is changed."""
    return answer.ask(a, body.question)


@router.post("/handoff", response_model=AssistantHandoff)
def hand_off(body: HandoffIn, a: Actor = Depends(limit("assistant_handoff", 10))):
    """A support ticket for a person. Dry run (payload returned and audited, nothing sent) unless HubSpot is enabled."""
    return handoff.hand_off(a, body.question.strip(), body.answer_status, (body.note or "").strip() or None)
