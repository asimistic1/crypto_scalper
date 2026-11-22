"""Chart Analysis — descriptive market context (no trade recommendations)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from core.config import ATR_PCT_BOUNDS, HIGHER_TIMEFRAMES
from core.levels import nearest_zones, structure_for_symbol
from core.models import Direction, Setup, TrendResult
from core.strategies import breakout_retest, trend_pullback
from core.strategies.types import StrategyContext
from core.trend import get_trend, slice_closed_at


@dataclass(frozen=True)
class ZoneSnapshot:
    role: str
    price_low: float
    price_high: float
    near_edge: float
    distance_pct: float
    touches: int
    strength: float


@dataclass(frozen=True)
class PatternSnapshot:
    label: str
    strategy: str
    direction: str
    warning: str


@dataclass
class ChartAnalysis:
    symbol_rest: str
    display_symbol: str
    timeframe: str
    as_of: datetime
    htf_trends: dict[str, TrendResult] = field(default_factory=dict)
    nearest_support: list[ZoneSnapshot] = field(default_factory=list)
    nearest_resistance: list[ZoneSnapshot] = field(default_factory=list)
    atr_pct: float = 0.0
    volatility_state: str = ""
    rsi_14: float | None = None
    macd_state: str = ""
    vwap_position: str = ""
    close: float = 0.0
    patterns: list[PatternSnapshot] = field(default_factory=list)
    context_notes: tuple[str, ...] = ()


def _volatility_label(tf: str, atr_pct: float) -> str:
    lo, hi = ATR_PCT_BOUNDS.get(tf, (0.1, 5.0))
    if atr_pct < lo:
        return "low"
    if atr_pct > hi:
        return "high"
    return "normal"


def _macd_label(row: pd.Series) -> str:
    hist = row.get("macd_hist")
    macd = row.get("macd")
    sig = row.get("macd_signal")
    if pd.isna(hist) or pd.isna(macd) or pd.isna(sig):
        return "unavailable"
    if hist > 0 and macd > sig:
        return "bullish momentum"
    if hist < 0 and macd < sig:
        return "bearish momentum"
    return "neutral / mixed"


def _vwap_label(close: float, vwap: float | None) -> str:
    if vwap is None or not pd.notna(vwap):
        return "VWAP unavailable"
    if close > vwap * 1.001:
        return "above session VWAP"
    if close < vwap * 0.999:
        return "below session VWAP"
    return "near VWAP"


def _zone_rows(zones, role: str, price: float, limit: int = 3) -> list[ZoneSnapshot]:
    out: list[ZoneSnapshot] = []
    for z in zones[:limit]:
        near = float(z.price_high if role == "support" else z.price_low)
        dist_pct = 100.0 * abs(price - near) / price if price else 0.0
        out.append(
            ZoneSnapshot(
                role=role,
                price_low=float(z.price_low),
                price_high=float(z.price_high),
                near_edge=near,
                distance_pct=dist_pct,
                touches=int(z.touches),
                strength=float(getattr(z, "strength", z.touches)),
            )
        )
    return out


def _pattern_label(strategy: str, direction: Direction) -> str:
    side = "Bullish" if direction == Direction.LONG else "Bearish"
    if strategy == "trend_pullback":
        return f"{side} pullback pattern at EMA21"
    if strategy == "breakout_retest":
        return f"{side} breakout retest pattern"
    return f"{side} {strategy.replace('_', ' ')}"


def detect_patterns(ctx: StrategyContext, *, warning_for) -> list[PatternSnapshot]:
    patterns: list[PatternSnapshot] = []
    for fn, name in ((trend_pullback.detect, "trend_pullback"), (breakout_retest.detect, "breakout_retest")):
        c = fn(ctx)
        if c is None:
            continue
        patterns.append(
            PatternSnapshot(
                label=_pattern_label(name, c.direction),
                strategy=name,
                direction=c.direction.value,
                warning=warning_for(name),
            )
        )
    return patterns


def build_chart_analysis(
    display_symbol: str,
    symbol_rest: str,
    timeframe: str,
    ltf_df: pd.DataFrame,
    htf_dfs: dict[str, pd.DataFrame],
    setup: Setup,
    *,
    show_patterns: bool,
    warning_for,
    enriched_row: pd.Series | None = None,
    tick_size: float = 0.01,
) -> ChartAnalysis:
    row = enriched_row if enriched_row is not None else ltf_df.iloc[-1]
    as_of = setup.as_of
    close = float(row["close"])
    atr = float(row.get("atr_14") or 0.0)
    atr_pct = 100.0 * atr / close if close and atr else 0.0

    htf: dict[str, TrendResult] = {}
    for tf in (*HIGHER_TIMEFRAMES.get(timeframe, ()), "1d", timeframe):
        df = htf_dfs.get(tf) if tf != timeframe else ltf_df
        if df is not None and not df.empty:
            htf[tf] = get_trend(slice_closed_at(df, as_of), as_of)

    _, zones = structure_for_symbol(ltf_df, as_of, atr, None)
    below, above = nearest_zones(zones, close, 3)

    patterns: list[PatternSnapshot] = []
    if show_patterns:
        closed = slice_closed_at(ltf_df, as_of)
        htf_tr = {tf: get_trend(slice_closed_at(htf_dfs[tf], as_of), as_of) for tf in htf_dfs}
        ctx = StrategyContext(
            symbol=symbol_rest,
            timeframe=timeframe,
            df=closed,
            htf_trends=htf_tr,
            zones=tuple(zones),
            tick_size=tick_size,
            as_of=as_of,
        )
        patterns = detect_patterns(ctx, warning_for=warning_for)

    rsi = float(row["rsi_14"]) if pd.notna(row.get("rsi_14")) else None
    vwap = row.get("vwap_daily")
    vwap_f = float(vwap) if pd.notna(vwap) else None

    notes = tuple(r for r in setup.reasons if not r.startswith("✖"))[:6]

    return ChartAnalysis(
        symbol_rest=symbol_rest,
        display_symbol=display_symbol,
        timeframe=timeframe,
        as_of=as_of,
        htf_trends=htf or setup.htf_trends,
        nearest_support=_zone_rows(below, "support", close),
        nearest_resistance=_zone_rows(above, "resistance", close),
        atr_pct=atr_pct,
        volatility_state=_volatility_label(timeframe, atr_pct),
        rsi_14=rsi,
        macd_state=_macd_label(row),
        vwap_position=_vwap_label(close, vwap_f),
        close=close,
        patterns=patterns,
        context_notes=notes,
    )