"""Skin backend: text-prompt -> parametric skin description.

Turns a natural-language style prompt into a bounded skin specification that the
mesh stage can realise. Backend availability is deployment-gated.
"""
from __future__ import annotations

from typing import Any


class SkinBackendError(Exception):
    """Raised when the skin backend cannot produce a specification."""


def generate_skin(prompt: str) -> dict[str, Any]:
    """Return a skin specification for ``prompt``."""
    raise SkinBackendError("skin backend is not configured in this build")
