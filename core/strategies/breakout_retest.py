"""
Breakout + retest strategy — trade continuation after structure break.
Uses Zone.origin (pivot type), not role, so flipped zones still match breakouts.
"""

from __future__ import annotations

from core.models import Direction, Zone
from core.strategies._helpers import (
    closed_df_at,
    htf_not_bearish,
    htf_not_bullish,
    signal_row,
    zones_with_origin,
)
from core.strategies.types import StrategyCandidate, StrategyContext

LOOKBACK = 10
VOL_MIN = 1.5


def _window_prev(df, lookback: int = LOOKBACK):
    """Closed bars strictly before the signal candle."""
    if len(df) < lookback + 1:
        return None
    return df.iloc[-(lookback + 1) : -1]


def _find_breakout_long(df, zones: list[Zone], lookback: int = LOOKBACK) -> Zone | None:
    window = _window_prev(df, lookback)
    if window is None:
        return None
    close = window["close"].to_numpy(dtype=float)
    vol = window["volume_ratio"].fillna(0.0).to_numpy(dtype=float)
    hi_zones = zones_with_origin(zones, "high")
    for z in hi_zones:
        broke = (close > z.price_high) & (vol >= VOL_MIN)
        if broke.any():
            return z
    return None


def _find_breakout_short(df, zones: list[Zone], lookback: int = LOOKBACK) -> Zone | None:
    window = _window_prev(df, lookback)
    if window is None:
        return None
    close = window["close"].to_numpy(dtype=float)
    vol = window["volume_ratio"].fillna(0.0).to_numpy(dtype=float)
    lo_zones = zones_with_origin(zones, "low")
    for z in lo_zones:
        broke = (close < z.price_low) & (vol >= VOL_MIN)
        if broke.any():
            return z
    return None


def _retest_long(df, zone: Zone) -> bool:
    cur = signal_row(df)
    touched = float(cur["low"]) <= zone.price_high
    held = float(cur["close"]) >= zone.price_low
    closes_up = float(cur["close"]) > float(cur["open"])
    return touched and held and closes_up


def _retest_short(df, zone: Zone) -> bool:
    cur = signal_row(df)
    touched = float(cur["high"]) >= zone.price_low
    held = float(cur["close"]) <= zone.price_high
    closes_down = float(cur["close"]) < float(cur["open"])
    return touched and held and closes_down


def detect(ctx: StrategyContext) -> StrategyCandidate | None:
    df = closed_df_at(ctx.df, ctx.as_of)
    if len(df) < 12:
        return None

    cur = signal_row(df)
    sig_time = cur["time"]
    sig_time = sig_time.to_pydatetime() if hasattr(sig_time, "to_pydatetime") else sig_time
    zone_list = list(ctx.zones)

    if htf_not_bearish(ctx.htf_trends):
        zone = _find_breakout_long(df, zone_list)
        if zone and _retest_long(df, zone):
            vol = float(cur["volume_ratio"])
            reasons = (
                "✔ Broke resistance with volume",
                f"✔ Retest held above {zone.price_low:.4f}",
                "✔ HTF not bearish",
                f"✔ volume_ratio {vol:.2f}",
            )
            conf = float(cur["close"]) > float(cur["open"])
            return StrategyCandidate(
                Direction.LONG,
                "breakout_retest",
                sig_time,
                reasons,
                vol * 20.0,
                confirmation_candle=conf,
                reacted_zone=zone,
                reaction_source="zone",
            )

    if htf_not_bullish(ctx.htf_trends):
        zone = _find_breakout_short(df, zone_list)
        if zone and _retest_short(df, zone):
            vol = float(cur["volume_ratio"])
            reasons = (
                "✔ Broke support with volume",
                f"✔ Retest held below {zone.price_high:.4f}",
                "✔ HTF not bullish",
                f"✔ volume_ratio {vol:.2f}",
            )
            conf = float(cur["close"]) < float(cur["open"])
            return StrategyCandidate(
                Direction.SHORT,
                "breakout_retest",
                sig_time,
                reasons,
                vol * 20.0,
                confirmation_candle=conf,
                reacted_zone=zone,
                reaction_source="zone",
            )
    return None