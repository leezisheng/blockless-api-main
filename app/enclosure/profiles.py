"""Board enclosure profiles.

Curated per-board case parameters (board footprint, mount posts, port cut-outs)
loaded from ``content/enclosure/board_profiles``.
"""
from __future__ import annotations

from typing import Any


class ProfileNotFound(Exception):
    """Raised when no enclosure profile exists for the requested board."""


class ProfileInvalid(Exception):
    """Raised when a stored enclosure profile fails validation."""


def load_profile(board_slug: str) -> dict[str, Any]:
    """Load and validate the enclosure profile for ``board_slug``."""
    raise ProfileNotFound(board_slug)
