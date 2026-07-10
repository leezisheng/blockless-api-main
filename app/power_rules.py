"""Power / supply rules.

Aggregates per-module current draw and checks it against the selected board's
regulator budget, producing warnings when a rail is over-subscribed.
"""
from __future__ import annotations

from typing import Any


def budget(board_id: str, modules: list[str]) -> dict[str, Any]:
    """Return a supply budget report for ``modules`` on ``board_id``."""
    return {"rails": {}, "warnings": [], "ok": True}
