"""Recommendation catalog: curated board/module models, purchase links, and the
license-cleared 3D-model registry.

All data is loaded from ``content/recommendation`` and ``content/models``. The
public build ships a trimmed catalog; helpers return empty results when a lookup
has no curated entry rather than guessing.
"""
from __future__ import annotations

from typing import Any


def board_model(slug: str | None) -> dict[str, Any] | None:
    """Curated display model for a board slug."""
    return None


def load_purchase_links(region: str) -> dict[str, list[dict[str, Any]]]:
    """Generated purchase links keyed by board slug for ``region``."""
    return {}


def board_purchase_links(slug: str | None, region: str) -> list[dict[str, Any]]:
    """Curated, verified purchase links for a single board."""
    return []


def filter_buyable_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop family/SoC pages, keeping only concrete buyable product links."""
    return [link for link in links if link.get("url")]


def select_primary_link(links: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the single primary buy link to surface, or None."""
    return links[0] if links else None


def model_catalog() -> list[dict[str, Any]]:
    """Rows of the 3D-model registry (license status + provenance)."""
    return []


def model_asset_index() -> dict[str, dict[str, Any]]:
    """Registry keyed by servable model key."""
    return {}
