"""
Higher-timeframe and local trend bias (pure, no look-ahead).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.levels import find_swings, swings_confirmed_as_of
from core.models import TrendBias, TrendResult


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def slice_closed_at(df: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """
    Rows whose candle has fully closed at as_of.
    HTF rule: use close_time <= as_of when available.
    """
    as_of = _aware(as_of)
    if df.empty:
        return df.copy()
    work = df.copy()
    if "close_time" in work.columns:
        ct = work["close_time"]
        if pd.api.types.is_integer_dtype(ct):
            mask = pd.to_datetime(ct, unit="ms", utc=True) <= as_of
        else:
            mask = pd.to_datetime(ct, utc=True) <= as_of
        return work.loc[mask].reset_index(drop=True)
    times = pd.to_datetime(work["time"], utc=True)
    return work.loc[times <= as_of].reset_index(drop=True)


def _swing_structure(swings: list, kind: str) -> list[float]:
    return [s.price for s in swings if s.kind == kind]


def _structure_bias(swings_at_as_of: list) -> tuple[TrendBias | None, str]:
    highs = _swing_structure(swings_at_as_of, "high")
    lows = _swing_structure(swings_at_as_of, "low")
    if len(highs) < 2 or len(lows) < 2:
        return None, "insufficient swing history"

    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    hh_hl = h2 > h1 and l2 > l1
    lh_ll = h2 < h1 and l2 < l1
    if hh_hl:
        return TrendBias.BULLISH, "HH+HL structure"
    if lh_ll:
        return TrendBias.BEARISH, "LH+LL structure"
    return TrendBias.NEUTRAL, "mixed swing structure"


def get_trend(df: pd.DataFrame, as_of: datetime) -> TrendResult:
    """
    Trend bias from price vs EMAs, EMA stack, and last confirmed swings.
    df should already include ema_50 and ema_200 (from add_all_indicators).
    """
    required = {"close", "ema_50", "ema_200"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"get_trend missing columns: {missing}")

    closed = slice_closed_at(df, as_of)
    if closed.empty:
        return TrendResult(TrendBias.NEUTRAL, ("no closed bars at as_of",))

    row = closed.iloc[-1]
    close = float(row["close"])
    ema50 = float(row["ema_50"])
    ema200 = float(row["ema_200"])
    reasons: list[str] = []

    bullish_ema = close > ema50 and close > ema200 and ema50 > ema200
    bearish_ema = close < ema50 and close < ema200 and ema50 < ema200

    swings = swings_confirmed_as_of(find_swings(closed), as_of)
    struct_bias, struct_reason = _structure_bias(swings)
    if struct_reason:
        reasons.append(struct_reason)

    if bullish_ema and struct_bias in (TrendBias.BULLISH, TrendBias.NEUTRAL, None):
        reasons.extend(["price above EMA50/200", "EMA50 > EMA200"])
        if struct_bias == TrendBias.BEARISH:
            return TrendResult(TrendBias.NEUTRAL, tuple(reasons + ["EMA stack bullish but swings bearish"]))
        return TrendResult(TrendBias.BULLISH, tuple(reasons))

    if bearish_ema and struct_bias in (TrendBias.BEARISH, TrendBias.NEUTRAL, None):
        reasons.extend(["price below EMA50/200", "EMA50 < EMA200"])
        if struct_bias == TrendBias.BULLISH:
            return TrendResult(TrendBias.NEUTRAL, tuple(reasons + ["EMA stack bearish but swings bullish"]))
        return TrendResult(TrendBias.BEARISH, tuple(reasons))

    if struct_bias is not None and struct_bias != TrendBias.NEUTRAL:
        reasons.append("EMAs mixed — leaning on swing structure")
        return TrendResult(struct_bias, tuple(reasons))

    reasons.append("EMAs and structure neutral/mixed")
    return TrendResult(TrendBias.NEUTRAL, tuple(reasons))


def htf_trends(
    frames: dict[str, pd.DataFrame],
    as_of: datetime,
) -> dict[str, TrendResult]:
    """Run get_trend on each HTF dataframe, each sliced with the same as_of."""
    out: dict[str, TrendResult] = {}
    for tf, frame in frames.items():
        out[tf] = get_trend(slice_closed_at(frame, as_of), as_of)
    return out