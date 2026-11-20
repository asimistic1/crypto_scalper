"""
Trend pullback strategy — enter with HTF trend after a shallow LTF pullback.
"""

from __future__ import annotations

import pandas as pd

from core.models import Direction
from core.strategies._helpers import (
    bearish_engulfing,
    bullish_engulfing,
    closed_df_at,
    htf_allows_long,
    htf_allows_short,
    prev_row,
    resistance_zones,
    signal_row,
    support_zones,
    touched_resistance,
    touched_support,
)
from core.strategies.types import StrategyCandidate, StrategyContext


def _pullback_long(df, zones, n: int = 3) -> bool:
    sup = support_zones(zones)
    tail = df.iloc[-n:]
    for _, row in tail.iterrows():
        if row["low"] <= row["ema_21"] <= row["high"]:
            return True
        if touched_support(row, sup):
            return True
        vwap = row.get("vwap_daily")
        if pd.notna(vwap) and row["low"] <= float(vwap) <= row["high"]:
            return True
    return False


def _pullback_short(df, zones, n: int = 3) -> bool:
    res = resistance_zones(zones)
    tail = df.iloc[-n:]
    for _, row in tail.iterrows():
        if row["low"] <= row["ema_21"] <= row["high"]:
            return True
        if touched_resistance(row, res):
            return True
        vwap = row.get("vwap_daily")
        if pd.notna(vwap) and row["low"] <= float(vwap) <= row["high"]:
            return True
    return False


def detect(ctx: StrategyContext) -> StrategyCandidate | None:
    df = closed_df_at(ctx.df, ctx.as_of)
    if len(df) < 5:
        return None

    cur = signal_row(df)
    prev = prev_row(df)
    if prev is None:
        return None

    if htf_allows_long(ctx.htf_trends):
        if _pullback_long(df, ctx.zones):
            rsi = float(cur["rsi_14"])
            prev_rsi = float(prev["rsi_14"])
            rsi_ok = 40.0 <= rsi <= 55.0 and rsi > prev_rsi
            conf = float(cur["close"]) > float(prev["high"]) or bullish_engulfing(cur, prev)
            vol_ok = float(cur["volume_ratio"]) >= 1.0
            if rsi_ok and conf and vol_ok:
                reasons: list[str] = []
                reasons.extend(
                    [
                        "✔ HTF allows long",
                        "✔ Pullback to EMA21/zone/VWAP",
                        f"✔ RSI {rsi:.1f} rising",
                        "✔ Bullish confirmation candle",
                        f"✔ volume_ratio {float(cur['volume_ratio']):.2f}",
                    ]
                )
                pick = rsi + float(cur["volume_ratio"]) * 10.0
                t = cur["time"]
                sig_time = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
                return StrategyCandidate(
                    Direction.LONG,
                    "trend_pullback",
                    sig_time,
                    tuple(reasons),
                    pick,
                )

    if htf_allows_short(ctx.htf_trends):
        if _pullback_short(df, ctx.zones):
            rsi = float(cur["rsi_14"])
            prev_rsi = float(prev["rsi_14"])
            rsi_ok = 45.0 <= rsi <= 60.0 and rsi < prev_rsi
            conf = float(cur["close"]) < float(prev["low"]) or bearish_engulfing(cur, prev)
            vol_ok = float(cur["volume_ratio"]) >= 1.0
            if rsi_ok and conf and vol_ok:
                reasons = [
                    "✔ HTF allows short",
                    "✔ Pullback to EMA21/zone/VWAP",
                    f"✔ RSI {rsi:.1f} falling",
                    "✔ Bearish confirmation candle",
                    f"✔ volume_ratio {float(cur['volume_ratio']):.2f}",
                ]
                pick = (100.0 - rsi) + float(cur["volume_ratio"]) * 10.0
                t = cur["time"]
                sig_time = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
                return StrategyCandidate(
                    Direction.SHORT,
                    "trend_pullback",
                    sig_time,
                    tuple(reasons),
                    pick,
                )
    return None