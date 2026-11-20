"""
In-memory last-good chart snapshots (per symbol / timeframe / limit), shared server-wide.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import pandas as pd

from core.data import PAKISTAN_TZ

_lock = threading.Lock()
_store: dict[tuple[str, str, int], dict[str, Any]] = {}


def chart_key(symbol: str, timeframe: str, limit: int) -> tuple[str, str, int]:
    return (symbol, timeframe, limit)


def save(
    symbol: str, timeframe: str, limit: int, df: pd.DataFrame
) -> None:
    """Remember a successful chart dataframe with a Pakistan-time timestamp."""
    key = chart_key(symbol, timeframe, limit)
    with _lock:
        _store[key] = {
            "df": df.copy(),
            "saved_at": datetime.now(PAKISTAN_TZ),
        }


def get(symbol: str, timeframe: str, limit: int) -> tuple[pd.DataFrame | None, datetime | None]:
    """Return cached df only when the key matches exactly."""
    key = chart_key(symbol, timeframe, limit)
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None, None
        return entry["df"].copy(), entry["saved_at"]