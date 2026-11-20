"""
Breakout + retest strategy — trade continuation after structure break.
"""

from __future__ import annotations

from core.models import Direction
from core.strategies._helpers import (
    closed_df_at,
    htf_not_bearish,
    htf_not_bullish,
    resistance_zones,
    signal_row,
    support_zones,
)
from core.strategies.types import StrategyCandidate, StrategyContext


def _find_breakout_long(df, res_zones, lookback: int = 10):
    if len(df) < lookback + 1:
        return None
    window = df.iloc[-(lookback + 1) : -1]
    for z in res_zones:
        for _, row in window.iterrows():
            if float(row["close"]) > z.price_high and float(row["volume_ratio"]) >= 1.5:
                return z
    return None


def _find_breakout_short(df, sup_zones, lookback: int = 10):
    if len(df) < lookback + 1:
        return None
    window = df.iloc[-(lookback + 1) : -1]
    for z in sup_zones:
        for _, row in window.iterrows():
            if float(row["close"]) < z.price_low and float(row["volume_ratio"]) >= 1.5:
                return z
    return None


def _retest_long(df, zone) -> bool:
    cur = signal_row(df)
    touched = float(cur["low"]) <= zone.price_high
    held = float(cur["close"]) >= zone.price_low
    closes_up = float(cur["close"]) > float(cur["open"])
    return touched and held and closes_up


def _retest_short(df, zone) -> bool:
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

    if htf_not_bearish(ctx.htf_trends):
        zone = _find_breakout_long(df, resistance_zones(ctx.zones))
        if zone and _retest_long(df, zone):
            vol = float(cur["volume_ratio"])
            reasons = (
                "✔ Broke resistance with volume",
                f"✔ Retest held above {zone.price_low:.4f}",
                "✔ HTF not bearish",
                f"✔ volume_ratio {vol:.2f}",
            )
            return StrategyCandidate(
                Direction.LONG,
                "breakout_retest",
                sig_time,
                reasons,
                vol * 20.0,
            )

    if htf_not_bullish(ctx.htf_trends):
        zone = _find_breakout_short(df, support_zones(ctx.zones))
        if zone and _retest_short(df, zone):
            vol = float(cur["volume_ratio"])
            reasons = (
                "✔ Broke support with volume",
                f"✔ Retest held below {zone.price_high:.4f}",
                "✔ HTF not bullish",
                f"✔ volume_ratio {vol:.2f}",
            )
            return StrategyCandidate(
                Direction.SHORT,
                "breakout_retest",
                sig_time,
                reasons,
                vol * 20.0,
            )
    return None