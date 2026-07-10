"""Module classifier: map a module name to its capability tokens + interface."""
from __future__ import annotations

from typing import Any


def classify(module: str) -> dict[str, Any] | None:
    """Return ``{capabilities, interface}`` for ``module`` or None when unknown."""
    return None
