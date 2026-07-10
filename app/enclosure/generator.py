"""Deterministic enclosure geometry planner + CAD export.

``plan_enclosure`` turns a curated board profile plus bounded user knobs into a
geometry descriptor (outer size, wall thickness, openings, DRC report);
``export_files`` renders that descriptor to STEP/STL through the CAD kernel.
The CAD kernel (cadquery/OCCT) is an optional enclosure-time dependency.
"""
from __future__ import annotations

from typing import Any


class ParamsInvalid(Exception):
    """Raised when enclosure knob values fall outside their allowed bounds."""


def plan_enclosure(board_slug: str, params: dict[str, Any], modules: list[str]) -> dict[str, Any]:
    """Plan a case for ``board_slug`` from ``params`` and the module list.

    Returns a geometry descriptor including a ``drc`` report. This deployment does
    not ship the geometry kernel, so planning is unavailable.
    """
    raise ParamsInvalid("enclosure planning is not available in this build")


def export_files(
    descriptor: dict[str, Any],
    out_dir: str,
    *,
    parts: list[str],
    formats: list[str],
) -> dict[str, str]:
    """Render ``descriptor`` to files under ``out_dir`` keyed by ``part.fmt``."""
    raise RuntimeError("enclosure_export_unavailable")
