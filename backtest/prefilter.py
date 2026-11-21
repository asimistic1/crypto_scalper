"""Vectorized superset mask — union of strategy necessary conditions (slightly loose)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def candidate_mask(df: pd.DataFrame, *, min_bars: int = 250) -> np.ndarray:
    """
    Boolean mask — must be a SUPERSET of any bar where build_setup returns LONG/SHORT.
    """
    n = len(df)
    mask = np.zeros(n, dtype=bool)
    if n < min_bars:
        return mask

    vol = df["volume_ratio"].fillna(0.0).to_numpy(dtype=float)
    rsi = df["rsi_14"].fillna(50.0).to_numpy(dtype=float)
    prev_rsi = np.empty_like(rsi)
    prev_rsi[0] = rsi[0]
    prev_rsi[1:] = rsi[:-1]

    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    prev_high = np.empty_like(close)
    prev_low = np.empty_like(close)
    prev_high[0] = close[0]
    prev_low[0] = close[0]
    prev_high[1:] = df["high"].to_numpy(dtype=float)[:-1]
    prev_low[1:] = df["low"].to_numpy(dtype=float)[:-1]

    long_pull = (
        (vol >= 0.95)
        & (rsi >= 38.0)
        & (rsi <= 57.0)
        & (rsi > prev_rsi - 0.5)
        & ((close > prev_high) | (close > open_))
    )
    short_pull = (
        (vol >= 0.95)
        & (rsi >= 43.0)
        & (rsi <= 62.0)
        & (rsi < prev_rsi + 0.5)
        & ((close < prev_low) | (close < open_))
    )

    vol_s = pd.Series(vol)
    # Previous 10 bars (excl. signal), + spike on signal bar
    prev10_max = vol_s.shift(1).rolling(10, min_periods=1).max().fillna(0.0).to_numpy()
    brk_vol = prev10_max >= 1.45
    brk_now = vol >= 1.5
    brk_candle = close != open_
    breakout = (brk_vol | brk_now) & brk_candle

    candidates = long_pull | short_pull | breakout
    mask[min_bars - 1 :] = candidates[min_bars - 1 :]
    return mask


def mask_fraction(mask: np.ndarray) -> float:
    return float(mask.sum()) / float(len(mask)) if len(mask) else 0.0