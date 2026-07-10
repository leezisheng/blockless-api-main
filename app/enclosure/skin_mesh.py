"""Skin mesh stage: realise a skin specification into printable geometry.

Consumes a skin spec + enclosure descriptor and produces a preview GLB plus the
split print halves, gated by a manufacturability report.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


class SkinMeshError(Exception):
    """Raised when the skin geometry cannot be built."""


class SkinUnavailable(Exception):
    """Raised when the mesh toolchain is not present in this deployment."""


@dataclass
class SkinBuild:
    manifest: dict[str, Any]
    gate_report: dict[str, Any] = field(default_factory=lambda: {"pass": False})
    preview_glb: bytes = b""
    halves: tuple[bytes, bytes] = (b"", b"")


def build_skin(spec: dict[str, Any], descriptor: dict[str, Any], *, bed: tuple[float, float]) -> SkinBuild:
    """Build printable skin geometry for ``spec`` fitted to ``descriptor``."""
    raise SkinUnavailable("skin mesh toolchain is not available in this build")


def manifest_key(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
