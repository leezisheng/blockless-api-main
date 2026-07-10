"""EasyEDA / LCEDA 3D model asset client.

Resolves and serves committed, license-cleared 3D component assets by file key.
Network fetching is deployment-gated; the public build serves only bundled assets.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MODELS_DIR = _ROOT / "content" / "models"


class EasyEdaError(Exception):
    """Raised on a missing, unreadable, or malformed model asset."""


def fetch_model_asset(file: str) -> tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for the committed asset named ``file``."""
    path = (_MODELS_DIR / file).resolve()
    if not path.is_relative_to(_MODELS_DIR.resolve()) or not path.is_file():
        raise EasyEdaError("asset_missing")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), content_type
