"""Vectorized superset mask for possible setup bars (loose on purpose)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _touches_ema21(row) -> bool:
    ema = row.get("ema_21")
    if pd.isna(ema):
        return False
    ema = float(ema)
    return float(row["low"]) <= ema <= float(row["high"])


def candidate_mask(df: pd.DataFrame, *, min_bars: int = 250) -> np.ndarray:
    """
    Boolean mask length n — superset of bars where build_setup might return LONG/SHORT.
    Intentionally loose; proof tests verify no false negatives.
    """
    n = len(df)
    mask = np.zeros(n, dtype=bool)
    if n < min_bars:
        return mask
    vol = df["volume_ratio"].fillna(0.0).to_numpy(dtype=float)
    rsi = df["rsi_14"].fillna(50.0).to_numpy(dtype=float)
    prev_rsi = np.roll(rsi, 1)
    prev_rsi[0] = rsi[0]
    ema_touch = np.array([_touches_ema21(df.iloc[i]) for i in range(n)], dtype=bool)

    # Pullback-like (loose RSI bands + volume + reaction)
    long_pull = (
        (vol >= 0.85)
        & (rsi >= 35.0)
        & (rsi <= 62.0)
        & ((rsi > prev_rsi - 1.5) | ema_touch)
    )
    short_pull = (
        (vol >= 0.85)
        & (rsi >= 38.0)
        & (rsi <= 68.0)
        & ((rsi < prev_rsi + 1.5) | ema_touch)
    )

    # Breakout-like: elevated volume somewhere recent
    vol_max = pd.Series(vol).rolling(12, min_periods=1).max().to_numpy()
    breakoutish = vol_max >= 1.2

    # Confirmation-ish candle (loose)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    prev_high = np.roll(df["high"].to_numpy(dtype=float), 1)
    prev_low = np.roll(df["low"].to_numpy(dtype=float), 1)
    bull_conf = (close > prev_high) | (close > open_)
    bear_conf = (close < prev_low) | (close < open_)

    candidates = (
        (long_pull & bull_conf)
        | (short_pull & bear_conf)
        | (breakoutish & (vol >= 1.0))
        | (ema_touch & (vol >= 0.9))
    )
    mask[min_bars - 1 :] = candidates[min_bars - 1 :]
    return mask