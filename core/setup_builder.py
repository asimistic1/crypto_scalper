"""
Trade setup construction — pure analysis (no network).

Turns closed candles + strategy signals into a typed Setup (or NO_TRADE).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Mapping

import pandas as pd

from core.config import (
    ATR_PCT_BOUNDS,
    FALLBACK_TP_R,
    LIMIT_ENTRY_MAX_DISTANCE_ATR,
    MIN_24H_QUOTE_VOLUME_USDT,
    MIN_NET_RR_TP1,
    MIN_SETUP_SCORE,
    MIN_SL_VS_COSTS,
    SCORE_WEIGHTS,
    SETUP_EXPIRY_CANDLES,
    SL_BUFFER_ATR,
    SL_MAX_ATR,
    SL_MIN_ATR,
    SLIPPAGE,
    STALE_DATA_MAX_PERIODS,
    TAKER_FEE,
)
from core.indicators import add_all_indicators
from core.levels import nearest_zones, structure_for_symbol
from core.models import (
    Direction,
    EntryType,
    ScoreBreakdown,
    Setup,
    SetupStatus,
    Zone,
    no_trade,
)
from core.strategies import run_strategies
from core.strategies.types import StrategyContext
from core.trend import htf_trends, slice_closed_at

logger = logging.getLogger(__name__)

MIN_CANDLES = 250
_TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _period_ms(tf: str) -> int:
    if tf not in _TF_MS:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return _TF_MS[tf]


def _tick_dec(tick_size: float) -> Decimal:
    return Decimal(str(tick_size))


def _round_price(value: float, tick: Decimal, rounding: str) -> float:
    q = Decimal(str(value)) / tick
    if rounding == "down":
        q = q.to_integral_value(rounding=ROUND_DOWN)
    else:
        q = q.to_integral_value(rounding=ROUND_UP)
    return float(q * tick)


def _data_stale(df: pd.DataFrame, timeframe: str, as_of: datetime) -> bool:
    if df.empty:
        return True
    as_of = _aware(as_of)
    last_ct = df["close_time"].iloc[-1]
    # close_time from Binance is milliseconds (numpy int64 is not isinstance int)
    if pd.isna(last_ct):
        return True
    try:
        last_ms = int(last_ct)
    except (TypeError, ValueError):
        last_ms = int(pd.Timestamp(last_ct).timestamp() * 1000)
    as_ms = int(_aware(as_of).timestamp() * 1000)
    return (as_ms - last_ms) > STALE_DATA_MAX_PERIODS * _period_ms(timeframe)


def _atr_pct(row: pd.Series) -> float:
    atr = float(row["atr_14"])
    close = float(row["close"])
    if close <= 0:
        return float("nan")
    return 100.0 * atr / close


def _in_range_chop(close: float, zones: list[Zone], atr: float, df: pd.DataFrame) -> bool:
    """True when price sits in the middle of recent range with no nearby structure."""
    tail = df.tail(50)
    if tail.empty:
        return True
    hi = float(tail["high"].max())
    lo = float(tail["low"].min())
    span = hi - lo
    if span <= 0 or atr <= 0:
        return False
    pos = (close - lo) / span
    mid_band = 0.3 <= pos <= 0.7
    if not mid_band:
        return False
    near = any(abs(close - z.mid) <= atr for z in zones)
    return not near


def _invalidation_low(
    swings,
    zones: list[Zone],
    entry: float,
    direction: Direction,
) -> float | None:
    if direction == Direction.LONG:
        lows = [s.price for s in swings if s.kind == "low" and s.price < entry]
        zlows = [z.price_low for z in zones if z.role == "support" and z.mid < entry]
        candidates = lows + zlows
        return min(candidates) if candidates else None
    highs = [s.price for s in swings if s.kind == "high" and s.price > entry]
    zhighs = [z.price_high for z in zones if z.role == "resistance" and z.mid > entry]
    candidates = highs + zhighs
    return max(candidates) if candidates else None


def _pick_limit_entry(
    direction: Direction,
    close: float,
    zones: list[Zone],
    atr: float,
) -> tuple[float, EntryType, str | None]:
    max_dist = LIMIT_ENTRY_MAX_DISTANCE_ATR * atr
    if direction == Direction.LONG:
        below, _ = nearest_zones(zones, close, 3)
        for z in below:
            edge = z.price_high
            if close - edge <= max_dist and edge < close:
                return edge, EntryType.LIMIT, f"support zone {z.price_low:.2f}-{z.price_high:.2f}"
    else:
        _, above = nearest_zones(zones, close, 3)
        for z in above:
            edge = z.price_low
            if edge - close <= max_dist and edge > close:
                return edge, EntryType.LIMIT, f"resistance zone {z.price_low:.2f}-{z.price_high:.2f}"
    return close, EntryType.MARKET, None


def _take_profits(
    direction: Direction,
    entry: float,
    sl: float,
    zones: list[Zone],
    atr: float,
    tick: Decimal,
) -> tuple[float, float, float, tuple[str, str, str]]:
    risk = abs(entry - sl)
    _, above = nearest_zones(zones, entry, 10)
    below, _ = nearest_zones(zones, entry, 10)

    levels: list[float] = []
    labels: list[str] = []
    if direction == Direction.LONG:
        opposites = [z for z in above if z.mid > entry]
        opposites.sort(key=lambda z: z.mid)
        for z in opposites[:3]:
            levels.append(z.price_low)
            labels.append(f"resistance {z.price_low:.2f}")
    else:
        opposites = [z for z in below if z.mid < entry]
        opposites.sort(key=lambda z: -z.mid)
        for z in opposites[:3]:
            levels.append(z.price_high)
            labels.append(f"support {z.price_high:.2f}")

    round_tp = "down" if direction == Direction.LONG else "up"
    while len(levels) < 3:
        r = FALLBACK_TP_R[len(levels)]
        if direction == Direction.LONG:
            raw = entry + r * risk
        else:
            raw = entry - r * risk
        levels.append(raw)
        labels.append(f"fallback {r}R")

    tps = tuple(_round_price(p, tick, round_tp) for p in levels[:3])
    return tps[0], tps[1], tps[2], (labels[0], labels[1], labels[2])


def _costs_usd_per_unit(entry: float) -> float:
    """Round-trip taker fees + slippage expressed in price units (per 1 unit of coin)."""
    return entry * (2 * TAKER_FEE + 2 * SLIPPAGE)


def _rr_triple(
    direction: Direction,
    entry: float,
    sl: float,
    tps: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float], float]:
    risk = abs(entry - sl)
    costs = _costs_usd_per_unit(entry)
    gross: list[float] = []
    net: list[float] = []
    for tp in tps:
        reward = (tp - entry) if direction == Direction.LONG else (entry - tp)
        if risk <= 0:
            gross.append(0.0)
            net.append(0.0)
            continue
        g = reward / risk
        net_r = (reward - costs) / (risk + costs) if (risk + costs) > 0 else 0.0
        gross.append(g)
        net.append(net_r)
    sl_pct = (risk / entry) * 100.0 if entry > 0 else 0.0
    return tuple(gross), tuple(net), sl_pct


def _opposing_before_tp1(
    direction: Direction,
    entry: float,
    tp1: float,
    zones: list[Zone],
) -> Zone | None:
    if direction == Direction.LONG:
        for z in zones:
            if z.role == "resistance" and entry < z.mid < tp1 and z.strength >= 2.0:
                return z
    else:
        for z in zones:
            if z.role == "support" and tp1 < z.mid < entry and z.strength >= 2.0:
                return z
    return None


def _score_setup(
    direction: Direction,
    row: pd.Series,
    htf: dict,
    strategy_reasons: tuple[str, ...],
    net_rr: tuple[float, float, float],
    atr_pct: float,
    timeframe: str,
    zone_label: str | None,
    opposing_penalty: float,
) -> tuple[float, ScoreBreakdown, list[str]]:
    w = SCORE_WEIGHTS
    reasons: list[str] = []

    bull_htf = sum(1 for t in htf.values() if t.bias.value == "bullish")
    bear_htf = sum(1 for t in htf.values() if t.bias.value == "bearish")
    if direction == Direction.LONG:
        if bear_htf == 0 and bull_htf >= 1:
            htf_s = float(w.htf)
            reasons.append("✔ HTF aligned for long")
        elif bear_htf == 0:
            htf_s = float(w.htf) * 0.5
            reasons.append("⚠ HTF neutral")
        else:
            htf_s = 0.0
            reasons.append("✖ HTF bearish present")
    else:
        if bull_htf == 0 and bear_htf >= 1:
            htf_s = float(w.htf)
            reasons.append("✔ HTF aligned for short")
        elif bull_htf == 0:
            htf_s = float(w.htf) * 0.5
            reasons.append("⚠ HTF neutral")
        else:
            htf_s = 0.0
            reasons.append("✖ HTF bullish present")

    level_s = float(w.level_quality) * 0.7 if zone_label else float(w.level_quality) * 0.4
    reasons.append("✔ Level context" if zone_label else "⚠ No limit zone edge")

    rsi = float(row["rsi_14"])
    if direction == Direction.LONG and 45 <= rsi <= 60:
        mom = float(w.momentum)
        reasons.append(f"✔ RSI {rsi:.1f} momentum")
    elif direction == Direction.SHORT and 40 <= rsi <= 55:
        mom = float(w.momentum)
        reasons.append(f"✔ RSI {rsi:.1f} momentum")
    else:
        mom = float(w.momentum) * 0.45
        reasons.append(f"⚠ RSI {rsi:.1f} outside ideal band")

    vr = float(row["volume_ratio"]) if pd.notna(row.get("volume_ratio")) else 0.0
    if vr >= 1.2:
        vol = float(w.volume)
        reasons.append(f"✔ volume_ratio {vr:.2f}")
    elif vr >= 1.0:
        vol = float(w.volume) * 0.7
        reasons.append(f"⚠ volume_ratio {vr:.2f}")
    else:
        vol = float(w.volume) * 0.3
        reasons.append(f"✖ volume_ratio {vr:.2f}")

    conf_lines = [r for r in strategy_reasons if "confirmation" in r.lower()]
    candle = float(w.candle_confirmation) if conf_lines else float(w.candle_confirmation) * 0.4
    reasons.append(conf_lines[0] if conf_lines else "⚠ Weak candle confirmation")

    n1 = net_rr[0]
    if n1 >= 2.0:
        rr_s = float(w.net_rr)
        reasons.append(f"✔ TP1 net R:R {n1:.2f}")
    elif n1 >= MIN_NET_RR_TP1:
        rr_s = float(w.net_rr) * 0.7
        reasons.append(f"⚠ TP1 net R:R {n1:.2f}")
    else:
        rr_s = 0.0
        reasons.append(f"✖ TP1 net R:R {n1:.2f}")

    bounds = ATR_PCT_BOUNDS.get(timeframe, (0.0, 100.0))
    lo, hi = bounds
    if lo <= atr_pct <= hi:
        vola = float(w.volatility)
        reasons.append(f"✔ ATR% {atr_pct:.2f}")
    else:
        vola = float(w.volatility) * 0.35
        reasons.append(f"⚠ ATR% {atr_pct:.2f} outside band")

    bd = ScoreBreakdown(
        htf=htf_s,
        level_quality=level_s,
        momentum=mom,
        volume=vol,
        candle_confirmation=candle,
        net_rr=rr_s,
        volatility=vola,
        penalties=opposing_penalty,
    )
    if opposing_penalty > 0:
        reasons.append(f"⚠ Opposing zone penalty −{opposing_penalty:.0f}")

    return bd.total, bd, reasons


def _order_valid(direction: Direction, entry: float, sl: float, tps: tuple[float, float, float]) -> bool:
    if not all(math.isfinite(x) and x > 0 for x in (entry, sl, *tps)):
        return False
    if direction == Direction.LONG:
        return sl < entry < tps[0] < tps[1] < tps[2]
    return sl > entry > tps[0] > tps[1] > tps[2]


def _expires_at(signal_time: datetime, timeframe: str) -> datetime:
    delta = timedelta(milliseconds=_period_ms(timeframe) * SETUP_EXPIRY_CANDLES)
    return _aware(signal_time) + delta


def build_setup(
    symbol: str,
    timeframe: str,
    ltf_df: pd.DataFrame,
    htf_dfs: Mapping[str, pd.DataFrame],
    daily_df: pd.DataFrame | None,
    as_of: datetime,
    tick_size: float,
    quote_volume_24h: float,
) -> Setup:
    """
    Main entry: returns Setup or NO_TRADE (with optional rejected_candidate).
    ltf_df must include OHLCV; indicators are computed on the closed slice only.
    """
    as_of = _aware(as_of)
    tick = _tick_dec(tick_size)

    ltf = slice_closed_at(ltf_df, as_of)
    if len(ltf) < MIN_CANDLES:
        return no_trade(symbol, timeframe, ("✖ Not enough closed candles (<250)",), as_of)

    if _data_stale(ltf, timeframe, as_of):
        return no_trade(symbol, timeframe, ("✖ Stale market data",), as_of)

    if quote_volume_24h < MIN_24H_QUOTE_VOLUME_USDT:
        return no_trade(
            symbol,
            timeframe,
            (f"✖ 24h quote volume below {MIN_24H_QUOTE_VOLUME_USDT:,.0f} USDT",),
            as_of,
        )

    ltf = add_all_indicators(ltf)
    row = ltf.iloc[-1]
    atr = float(row["atr_14"])
    close = float(row["close"])
    atr_pct = _atr_pct(row)
    bounds = ATR_PCT_BOUNDS.get(timeframe)
    if bounds:
        lo, hi = bounds
        if not (lo <= atr_pct <= hi):
            return no_trade(symbol, timeframe, (f"✖ ATR% {atr_pct:.2f} outside {lo}-{hi}",), as_of)

    swings, zones = structure_for_symbol(ltf, as_of, atr, daily_df)
    if _in_range_chop(close, zones, atr, ltf):
        return no_trade(symbol, timeframe, ("✖ Price mid-range, no nearby level",), as_of)

    htf_closed = {tf: slice_closed_at(frame, as_of) for tf, frame in htf_dfs.items()}
    htf_trend_map = htf_trends(
        {k: add_all_indicators(v) if len(v) else v for k, v in htf_closed.items()},
        as_of,
    )

    ctx = StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        df=ltf,
        htf_trends=htf_trend_map,
        zones=tuple(zones),
        as_of=as_of,
        tick_size=tick_size,
    )
    strat = run_strategies(ctx)
    if strat.conflict:
        return no_trade(symbol, timeframe, (strat.conflict_reason or "✖ Conflicting signals",), as_of)
    if strat.candidate is None:
        return no_trade(symbol, timeframe, ("✖ No strategy signal",), as_of)

    cand = strat.candidate
    direction = cand.direction

    raw_entry, entry_type, zone_label = _pick_limit_entry(direction, close, zones, atr)
    round_entry = "down" if direction == Direction.LONG else "up"
    if entry_type == EntryType.LIMIT:
        entry = _round_price(raw_entry, tick, round_entry)
    else:
        entry = _round_price(close, tick, round_entry)

    inv = _invalidation_low(swings, zones, entry, direction)
    if inv is None:
        return no_trade(symbol, timeframe, ("✖ No invalidation structure for stop",), as_of)

    if direction == Direction.LONG:
        sl_raw = inv - SL_BUFFER_ATR * atr
        sl = _round_price(sl_raw, tick, "down")
        risk = entry - sl
    else:
        sl_raw = inv + SL_BUFFER_ATR * atr
        sl = _round_price(sl_raw, tick, "up")
        risk = sl - entry

    if risk < SL_MIN_ATR * atr or risk > SL_MAX_ATR * atr:
        return no_trade(symbol, timeframe, ("✖ Stop distance does not fit ATR band",), as_of)

    tp1, tp2, tp3, tp_labels = _take_profits(direction, entry, sl, zones, atr, tick)
    gross_rr, net_rr, sl_pct = _rr_triple(direction, entry, sl, (tp1, tp2, tp3))

    costs = _costs_usd_per_unit(entry)
    if risk < MIN_SL_VS_COSTS * costs:
        return no_trade(symbol, timeframe, ("✖ Stop smaller than fee/slippage floor",), as_of)

    if net_rr[0] < MIN_NET_RR_TP1:
        return no_trade(symbol, timeframe, (f"✖ TP1 net R:R {net_rr[0]:.2f} < {MIN_NET_RR_TP1}",), as_of)

    opposing = _opposing_before_tp1(direction, entry, tp1, zones)
    opp_penalty = float(SCORE_WEIGHTS.opposing_zone_penalty) if opposing else 0.0
    if opposing and net_rr[0] < MIN_NET_RR_TP1 * 1.05:
        return no_trade(symbol, timeframe, ("✖ Strong opposing zone before TP1",), as_of)

    score, breakdown, score_reasons = _score_setup(
        direction,
        row,
        htf_trend_map,
        cand.reasons,
        net_rr,
        atr_pct,
        timeframe,
        zone_label,
        opp_penalty,
    )

    all_reasons = tuple(cand.reasons + tuple(score_reasons))
    levels_used = tuple(filter(None, [zone_label, *tp_labels]))
    signal_time = _aware(cand.signal_candle_time)
    tp_pcts = tuple(abs(tp - entry) / entry * 100.0 for tp in (tp1, tp2, tp3))

    setup = Setup(
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        strategy=cand.strategy,
        entry=entry,
        entry_type=entry_type,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        sl_pct=sl_pct,
        tp_pcts=tp_pcts,
        gross_rr=gross_rr,
        net_rr=net_rr,
        score=score,
        breakdown=breakdown,
        reasons=all_reasons,
        htf_trends=htf_trend_map,
        levels_used=levels_used,
        signal_candle_time=signal_time,
        as_of=as_of,
        setup_id=Setup.make_setup_id(symbol, timeframe, direction, cand.strategy, signal_time),
        status=SetupStatus.ACTIVE,
        expires_at=_expires_at(signal_time, timeframe),
    )

    if not _order_valid(direction, entry, sl, (tp1, tp2, tp3)):
        logger.warning("Setup ordering invalid — rejecting")
        return no_trade(symbol, timeframe, ("✖ Invalid price ordering",), as_of)

    for g, n in zip(setup.gross_rr, setup.net_rr):
        if n >= g:
            return no_trade(symbol, timeframe, ("✖ Net R:R must stay below gross",), as_of)

    if score < MIN_SETUP_SCORE:
        return no_trade(
            symbol,
            timeframe,
            (f"✖ Setup quality score {score:.0f} < {MIN_SETUP_SCORE}",),
            as_of,
            rejected=setup,
        )

    return setup