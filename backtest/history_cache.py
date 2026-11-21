"""Load each (symbol, timeframe) once for simulation (OHLC only, no indicators)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.history import load_history


@dataclass
class OhlcFrame:
    symbol: str
    timeframe: str
    df: pd.DataFrame
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    close_time: np.ndarray


_cache: dict[tuple[str, str], OhlcFrame] = {}


def get_ohlc(symbol: str, tf: str) -> OhlcFrame:
    key = (symbol.upper(), tf)
    if key in _cache:
        return _cache[key]
    raw = load_history(symbol, tf)
    df = raw.copy()
    sim_cols = ["time", "open", "high", "low", "close", "close_time"]
    if not set(sim_cols).issubset(df.columns):
        df = df[[c for c in sim_cols if c in df.columns]].copy()
    frame = OhlcFrame(
        symbol=symbol.upper(),
        timeframe=tf,
        df=df,
        open=df["open"].to_numpy(dtype=np.float64),
        high=df["high"].to_numpy(dtype=np.float64),
        low=df["low"].to_numpy(dtype=np.float64),
        close=df["close"].to_numpy(dtype=np.float64),
        close_time=df["close_time"].to_numpy(dtype=np.int64),
    )
    _cache[key] = frame
    return frame


def clear_ohlc_cache() -> None:
    _cache.clear()


def atr14(frame: OhlcFrame) -> np.ndarray:
    """Wilder ATR(14) aligned to frame.df index (nan for first bars)."""
    h, l, c = frame.high, frame.low, frame.close
    n = len(c)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    prev_c = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)))
    atr = np.full(n, np.nan, dtype=np.float64)
    period = 14
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr