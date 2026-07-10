"""Module enclosure profiles.

Per-module footprint + mounting metadata used by the placement solver, loaded
from ``content/enclosure/module_profiles``.
"""
from __future__ import annotations

from typing import Any


def load(module: str) -> dict[str, Any] | None:
    """Return the enclosure profile for ``module`` or None when unknown."""
    return None


def known_modules() -> list[str]:
    return []
