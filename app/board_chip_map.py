"""Board -> chip family mapping."""
from __future__ import annotations


def chip_for_board(board_id: str) -> str | None:
    """Return the chip slug backing ``board_id``, or None when unmapped."""
    return None
