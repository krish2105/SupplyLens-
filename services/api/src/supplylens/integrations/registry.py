"""Which purchasing-system adapter this installation uses (settings.erp_adapter).

Only adapters that pass the conformance suite (tests/test_phase6_erp.py) and a qualification against their real system are
registered. Today that is the local sandbox alone; a name that is not registered refuses every ERP call instead of
guessing (docs/operations/erp-integration.md lists what qualifying a real adapter needs).
"""
from __future__ import annotations

from ..config import settings
from .contract import AdapterAuthError, ErpAdapter
from .sandbox_erp import ADAPTER as SANDBOX

REGISTERED: dict[str, ErpAdapter] = {SANDBOX.name: SANDBOX}


class UnregisteredAdapter(AdapterAuthError):
    """Configuration names an adapter this build does not have; treated like missing credentials (nothing is sent)."""


def adapter() -> ErpAdapter:
    found = REGISTERED.get(settings.erp_adapter)
    if found is None:
        raise UnregisteredAdapter(f"ERP adapter {settings.erp_adapter!r} is not registered in this build")
    return found
