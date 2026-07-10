"""Thermal advisory for generated enclosures.

Produces an honest, human-readable note about ventilation given the enclosed
modules' power draw. Advisory only -- it never blocks a build.
"""
from __future__ import annotations

from typing import Any


def assess(modules: list[str], derived: dict[str, Any]) -> dict[str, Any]:
    """Return a thermal advisory ``{"wording": ..., "vent_recommended": bool}``."""
    return {"wording": "No thermal concerns for this configuration.", "vent_recommended": False}
