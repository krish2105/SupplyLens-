"""Server-side role/operation matrix. Tenant administration does not imply spend authority."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from .db import control_session
from .demo import operation_locked

MATRIX: dict[str, set[str]] = {
    "viewer": {"read"},
    "planner": {"read", "forecast.run", "plan.run", "agent.start", "action.prepare", "action.edit",
                "action.reconcile", "alert.ack"},
    "approver": {"read", "action.approve", "action.reject", "action.reconcile", "alert.ack"},
    "tenant_admin": {"read", "admin.read", "admin.write", "action.reconcile", "alert.ack", "alert.evaluate",
                     "tenant.export", "tenant.delete"},
}


class Forbidden(Exception):
    def __init__(self, operation: str, role: str | None, message: str | None = None):
        super().__init__(message or f"role {role!r} may not perform {operation!r}")
        self.operation, self.role = operation, role


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    tenant_id: UUID
    role: str
    email: str

    def require(self, operation: str) -> None:
        if operation not in MATRIX.get(self.role, set()):
            raise Forbidden(operation, self.role)
        if operation_locked(operation):
            raise Forbidden(operation, self.role, f"{operation!r} is disabled in the public demo: its accounts are shared "
                                                  "by every visitor (administration, exports and deletion stay closed)")


def resolve_actor(user_id: UUID, tenant_id: UUID) -> Actor | None:
    """Re-read membership from server-controlled records on every call (revocation is immediate)."""
    with control_session() as s:
        row = s.execute(text(
            "SELECT m.role, u.email FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.user_id = :u AND m.tenant_id = :t AND u.active"), {"u": user_id, "t": tenant_id}).first()
    return Actor(user_id, tenant_id, row.role, row.email) if row else None
