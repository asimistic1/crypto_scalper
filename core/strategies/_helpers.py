"""Small shared checks for strategy modules."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.models import TrendBias, TrendResult, Zone
from core.trend import slice_closed_at


def closed_df_at(df: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    return slice_closed_at(df, as_of)


def signal_row(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


def prev_row(df: pd.DataFrame) -> pd.Series | None:
    if len(df) < 2:
        return None
    return df.iloc[-2]


def htf_allows_long(htf: dict[str, TrendResult]) -> bool:
    """Both bullish, or one bullish + one neutral — never bearish."""
    if not htf:
        return True
    vals = [t.bias for t in htf.values()]
    if any(v == TrendBias.BEARISH for v in vals):
        return False
    return any(v == TrendBias.BULLISH for v in vals) or all(v == TrendBias.NEUTRAL for v in vals)


def htf_allows_short(htf: dict[str, TrendResult]) -> bool:
    if not htf:
        return True
    vals = [t.bias for t in htf.values()]
    if any(v == TrendBias.BULLISH for v in vals):
        return False
    return any(v == TrendBias.BEARISH for v in vals) or all(v == TrendBias.NEUTRAL for v in vals)


def htf_not_bearish(htf: dict[str, TrendResult]) -> bool:
    return all(t.bias != TrendBias.BEARISH for t in htf.values())


def htf_not_bullish(htf: dict[str, TrendResult]) -> bool:
    return all(t.bias != TrendBias.BULLISH for t in htf.values())


def support_zones(zones: tuple[Zone, ...]) -> list[Zone]:
    return [z for z in zones if z.role == "support"]


def resistance_zones(zones: tuple[Zone, ...]) -> list[Zone]:
    return [z for z in zones if z.role == "resistance"]


def touched_support(row: pd.Series, zones: list[Zone]) -> Zone | None:
    for z in zones:
        if row["low"] <= z.price_high and row["close"] >= z.price_low:
            return z
    return None


def touched_resistance(row: pd.Series, zones: list[Zone]) -> Zone | None:
    for z in zones:
        if row["high"] >= z.price_low and row["close"] <= z.price_high:
            return z
    return None


def bullish_engulfing(cur: pd.Series, prev: pd.Series) -> bool:
    return (
        cur["close"] > prev["open"]
        and cur["open"] < prev["close"]
        and cur["close"] > prev["close"]
        and prev["close"] < prev["open"]
    )


def bearish_engulfing(cur: pd.Series, prev: pd.Series) -> bool:
    return (
        cur["close"] < prev["open"]
        and cur["open"] > prev["close"]
        and cur["close"] < prev["close"]
        and prev["close"] > prev["open"]
    )