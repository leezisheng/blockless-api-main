"""Curated driver package store (no network).

Read access over the curated driver-context catalog under ``content/packages``:
resolve a capability to candidate packages, fetch a package's driver context, and
list the capability taxonomy. The public build ships a trimmed catalog.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# (capability, keyword) taxonomy pairs; the public build ships an empty catalog.
CAPABILITY_KEYWORDS: list[tuple[str, str]] = []


def safe_context_filename(name: str, version: str) -> str:
    """Filesystem-safe filename for a driver context ``name@version``."""
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", f"{name}-{version}")
    return f"{slug}.json"


def resolve_capability(capability: str) -> list[dict[str, Any]]:
    """Candidate packages providing ``capability``."""
    return []


def driver_context(name: str, version: str) -> dict[str, Any] | None:
    """Load the curated driver context for ``name@version`` or None."""
    return None
