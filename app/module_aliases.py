"""Curated module alias table (near-synonyms -> canonical module slug)."""
from __future__ import annotations

MODULE_ALIASES: dict[str, str] = {}


def resolve(alias: str) -> str | None:
    return MODULE_ALIASES.get(alias.strip().lower())
