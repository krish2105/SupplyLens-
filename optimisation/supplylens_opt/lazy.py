"""Import a heavy module on first use, not at start-up.

The hosted API runs as a serverless function: every cold start imports the whole app before it answers, and OR-Tools,
pandas and LangGraph are most of that time while most requests never touch them.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class LazyModule:
    def __init__(self, name: str):
        self._name = name
        self._module: ModuleType | None = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return self._module

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)

    def __repr__(self) -> str:
        return f"<lazy module {self._name!r} ({'loaded' if self._module else 'not loaded'})>"
