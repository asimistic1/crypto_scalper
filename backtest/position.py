"""One open position per (symbol, timeframe) portfolio."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import SETUP_EXPIRY_CANDLES


def _sort_signals(sig: pd.DataFrame) -> pd.DataFrame:
    if sig.empty:
        return sig
    return sig.sort_values(["symbol", "timeframe", "close_time", "bar_index"], kind="mergesort")


def busy_until_bar(
    signal_bar: int,
    *,
    filled: bool,
    fill_bar: int | None,
    exit_bar: int | None,
    outcome: str,
) -> int:
    """Last bar index that blocks new signals (inclusive)."""
    if outcome in ("INVALIDATED", "EXPIRED", "NO_FILL") or not filled:
        return signal_bar + SETUP_EXPIRY_CANDLES
    if exit_bar is not None:
        return exit_bar
    if fill_bar is not None:
        return fill_bar
    return signal_bar + SETUP_EXPIRY_CANDLES


def exit_bar_from_close_time(close_time: np.ndarray, exit_time_ms: int) -> int:
    idx = int(np.searchsorted(close_time, exit_time_ms, side="right")) - 1
    return max(0, idx)