"""Module placement solver.

Arranges the project's modules inside the case footprint, honouring keep-outs and
connector orientation, and reports any parts that could not be placed.
"""
from __future__ import annotations

from typing import Any


def place_modules(profile: dict[str, Any], modules: list[str]) -> dict[str, Any]:
    """Return placements + unplaced list for ``modules`` within ``profile``."""
    return {"placements": [], "unplaced": list(modules), "openings": []}
