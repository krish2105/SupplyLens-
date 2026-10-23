"""The purchasing-system (ERP) adapter contract (Phase 6).

Every adapter, the local sandbox included, implements `ErpAdapter` and passes the conformance suite in
tests/test_phase6_erp.py. The dispatcher (actions/service.py) and synchronisation (integrations/sync.py) talk to the
target only through this boundary.

Rules an adapter must honour:
* Submission is idempotent on the caller's key: a repeated key returns the existing order, never a second one.
* Every order can be looked up by that key (read-back), and returns the target's own copy of the lines, totals, need-by
  date and status. The dispatcher compares it line by line with the approval; an adapter never "fixes" differences.
* Errors are classified, because the safe reaction differs:
    AdapterUnavailable  the target could not be reached or refused service; nothing was processed (retry later)
    AdapterAuthError    credentials missing, expired or revoked; nothing was processed (pause until fixed)
    AdapterRejected     the target refused this order on business grounds; nothing was created (never auto-retried)
    AdapterTimeout      the request may or may not have been applied (look up before anything is sent again)
    AdapterError        any other transient failure known not to have been applied (bounded retries)
* Receipts are exposed as an ordered feed (`sequence` strictly increasing), so a consumer can resume from a cursor and
  book each receipt once (its `receipt_id` is the idempotency key on our side).

Order statuses as the contract names them: OPEN, CONFIRMED (supplier acknowledged), RECEIVED, CANCELLED, REJECTED.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class AdapterError(Exception):
    """Transient failure; the request was not applied."""
    retryable = True


class AdapterUnavailable(AdapterError):
    """The target is down or refusing service. Nothing was processed."""


class AdapterAuthError(AdapterError):
    """Credentials are missing, expired or revoked. Nothing was processed; retrying cannot succeed until fixed."""
    retryable = False


class AdapterRejected(AdapterError):
    """The target refused the request on business grounds (blocked supplier, closed period, ...). Nothing was created."""
    retryable = False


class AdapterTimeout(AdapterError):
    """No answer: the request may or may not have been applied. Look the operation up before any resend."""


OPEN_STATUSES = ("OPEN", "CONFIRMED")
CLOSED_STATUSES = ("CANCELLED", "REJECTED")


@runtime_checkable
class ErpAdapter(Protocol):
    name: str

    def capabilities(self) -> dict:
        """Static description: operations supported, qualification status, idempotency and notes."""

    def health(self) -> dict:
        """Cheap authenticated call. Raises AdapterUnavailable or AdapterAuthError; returns details when healthy."""

    def submit_purchase_order(self, idempotency_key: str, caller_ref: str, payload: dict) -> dict:
        """Create the order. Returns {"po_number", "status", "duplicate"}; a repeated key returns the existing order."""

    def lookup_purchase_order(self, idempotency_key: str) -> dict | None:
        """The target's copy: po_number, supplier_id, lines, total_minor, currency, status, need_by, created_at."""

    def orders_for(self, caller_refs: list[str]) -> list[dict]:
        """Every order the target holds for these caller references (reconciliation sweeps)."""

    def cancel_purchase_order(self, idempotency_key: str, reason: str) -> dict:
        """Cancel the still-open order. Idempotent; raises AdapterRejected when the target will not cancel it."""

    def receipts_since(self, caller_refs: list[str], after_sequence: int, limit: int = 200) -> list[dict]:
        """Goods receipts against these orders with sequence > after_sequence, oldest first: receipt_id, sequence,
        po_number, caller_ref, idempotency_key, sku_id, location_id, quantity, received_on."""
