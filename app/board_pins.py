"""Board pin metadata + the full board selection catalog.

Exposes the board picker universe and, per board, whether its chip has an
authoritative pin-fact table (``pin_allocation_supported``). Boards without one
are still selectable for firmware but never get pins auto-allocated.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_BOARDS_DIR = _ROOT / "content" / "boards"


def list_catalog() -> list[dict[str, Any]]:
    """All selectable boards with the pin-allocation support flag."""
    catalog: list[dict[str, Any]] = []
    if not _BOARDS_DIR.is_dir():
        return catalog
    for path in sorted(_BOARDS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        catalog.append(
            {
                "board_id": data.get("board_id", path.stem),
                "display_name": data.get("display_name", path.stem),
                "chip_family": data.get("chip_family"),
                "pin_allocation_supported": bool(data.get("pin_allocation_supported", False)),
            }
        )
    return catalog


def exposed_pins(board_id: str) -> list[str] | None:
    """The board's exposed GPIO overlay, or None when unknown."""
    return None
