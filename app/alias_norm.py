"""Alias normalization: canonicalize user/model part names to catalog slugs."""
from __future__ import annotations


def normalize(name: str) -> str:
    """Return the canonical catalog slug for ``name`` (identity when unmapped)."""
    return name.strip().lower().replace(" ", "_")
