from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import board_pins


ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()


def _safe_content_path(base: Path, name: str, suffix: str) -> Path:
    root = base.resolve()
    path = (base / f"{name}{suffix}").resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail={"error": "content_not_found"})
    return path


@router.get("/v1/boards")
def boards() -> dict:
    entries = []
    for path in sorted((ROOT / "content" / "boards").glob("*.json")):
        body = path.read_bytes()
        data = json.loads(body.decode("utf-8"))
        board_id = data.get("board_id")
        if not board_id:
            # Skip a malformed board file rather than 500 the whole listing.
            continue
        entries.append({
            "board_id": board_id,
            "display_name": data.get("display_name", board_id),
            "chip_family": data.get("chip_family"),
            "detail_url": f"/v1/boards/{board_id}",
            "detail_sha256": hashlib.sha256(body).hexdigest(),
        })
    return {
        "version": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        "builtin": entries,
        "community": [],
    }


@router.get("/v1/boards/catalog")
def boards_catalog() -> dict:
    """The full 216-board selection universe (all micropython.org/download boards).

    Each entry carries `pin_allocation_supported` — the pin_allocation_supported_gate — so
    the picker can offer every board for firmware while only auto-allocating pins on boards
    whose chip has an authoritative fact table (others fail loudly instead of guessing)."""
    boards_list = board_pins.list_catalog()
    supported = sum(1 for b in boards_list if b["pin_allocation_supported"])
    version = hashlib.sha256(json.dumps(boards_list, sort_keys=True).encode()).hexdigest()
    return {
        "version": version,
        "board_count": len(boards_list),
        "pin_supported_count": supported,
        "boards": boards_list,
    }


@router.get("/v1/boards/{board_id}")
def board(board_id: str) -> dict:
    path = _safe_content_path(ROOT / "content" / "boards", board_id, ".json")
    if not path.exists():
        raise HTTPException(status_code=404, detail={"error": "board_not_found"})
    return json.loads(path.read_text(encoding="utf-8"))
