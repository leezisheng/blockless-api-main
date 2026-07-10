"""Deterministic pin allocator.

Given a chip pin-fact table, an optional board exposed-pin overlay, and the
analyze-phase device list, assign MCU pins in code. Fail-fast: when a required
capability cannot be satisfied it raises ``AllocationError`` instead of inventing
a pin.
"""
from __future__ import annotations

from typing import Any

KNOWN_INTERFACES = {"i2c", "spi", "uart", "gpio_out", "gpio_in", "adc"}


class AllocationError(Exception):
    """Raised when pins cannot be allocated from authoritative facts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def allocate(chip: dict[str, Any], devices: list[dict[str, Any]], *, exposed_pins: list[str] | None = None) -> dict[str, Any]:
    """Allocate pins for ``devices`` against the ``chip`` fact table.

    The pin-fact tables are not bundled in the public build, so allocation fails
    loudly rather than guessing.
    """
    raise AllocationError("pin_facts_unavailable", "chip pin-fact tables are not available in this build")
