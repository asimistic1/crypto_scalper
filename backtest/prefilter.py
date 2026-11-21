"""Vectorized superset mask — union of strategy necessary conditions (slightly loose).

Documented superset arms (must include every LONG/SHORT from build_setup):

trend_pullback LONG: volume_ratio ≥ 0.95, RSI 38–57, RSI > prev RSI − 0.5,
    (close > prev high OR close > open).
trend_pullback SHORT: volume_ratio ≥ 0.95, RSI 43–62, RSI < prev RSI + 0.5,
    (close < prev low OR close < open).

breakout_retest LONG (zone origin high): signal closes up; in the previous 10
    closed bars, ∃ bar with volume_ratio ≥ 1.5 and close > signal low (necessary
    for a break above zone.price_high when retest low ≤ zone high).
breakout_retest SHORT (origin low): signal closes down; ∃ bar in prev 10 with
    volume_ratio ≥ 1.5 and close < signal high.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

VOL_BREAK = 1.5
VOL_PULL = 0.95
LOOKBACK = 10


def _prev_n_breakout_long(
    close: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    n: int = LOOKBACK,
) -> np.ndarray:
    """Signal closes up and a prior bar had vol spike with close > signal low."""
    closes_up = close > open_
    any_hit = np.zeros(len(close), dtype=bool)
    for k in range(1, n + 1):
        vol_k = np.concatenate([np.zeros(k), vol[:-k]])
        close_k = np.concatenate([np.zeros(k), close[:-k]])
        any_hit |= (vol_k >= VOL_BREAK) & (close_k > low)
    return closes_up & any_hit


def _prev_n_breakout_short(
    close: np.ndarray, high: np.ndarray, vol: np.ndarray, open_: np.ndarray, n: int = LOOKBACK
) -> np.ndarray:
    closes_down = close < open_
    any_hit = np.zeros(len(close), dtype=bool)
    for k in range(1, n + 1):
        vol_k = np.concatenate([np.zeros(k), vol[:-k]])
        close_k = np.concatenate([np.zeros(k), close[:-k]])
        any_hit |= (vol_k >= VOL_BREAK) & (close_k < high)
    return closes_down & any_hit


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
    low = df["low"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    prev_high = np.empty_like(close)
    prev_low = np.empty_like(close)
    prev_high[0] = close[0]
    prev_low[0] = close[0]
    prev_high[1:] = high[:-1]
    prev_low[1:] = low[:-1]

    long_pull = (
        (vol >= VOL_PULL)
        & (rsi >= 38.0)
        & (rsi <= 57.0)
        & (rsi > prev_rsi - 0.5)
        & ((close > prev_high) | (close > open_))
    )
    short_pull = (
        (vol >= VOL_PULL)
        & (rsi >= 43.0)
        & (rsi <= 62.0)
        & (rsi < prev_rsi + 0.5)
        & ((close < prev_low) | (close < open_))
    )

    brk_long = _prev_n_breakout_long(close, low, vol, open_)
    brk_short = _prev_n_breakout_short(close, high, vol, open_)

    candidates = long_pull | short_pull | brk_long | brk_short
    mask[min_bars - 1 :] = candidates[min_bars - 1 :]
    return mask


def mask_fraction(mask: np.ndarray) -> float:
    return float(mask.sum()) / float(len(mask)) if len(mask) else 0.0