"""
Input validation at trust boundaries (UI → analysis core).
"""

from __future__ import annotations

import re

from core.config import TIMEFRAMES_ALLOWED

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")


def validate_symbol_rest(symbol: str) -> tuple[bool, str]:
    """REST symbol like BTCUSDT (no slash)."""
    sym = symbol.upper().strip()
    if not _SYMBOL_RE.match(sym):
        return False, "Symbol must be a USDT perpetual like BTCUSDT."
    return True, sym


def validate_timeframe(tf: str) -> tuple[bool, str]:
    if tf not in TIMEFRAMES_ALLOWED:
        return False, f"Timeframe must be one of {TIMEFRAMES_ALLOWED}."
    return True, tf


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))