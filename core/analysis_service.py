"""
Run trade setup analysis (data fetch + build_setup + overlays).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from core.config import HIGHER_TIMEFRAMES
from core.exchange_info import binance_server_time_ms, price_precision, tick_size
from core.levels import find_swings, nearest_zones, structure_for_symbol, swings_confirmed_as_of
from core.models import Setup
from core.security import validate_symbol_rest


@dataclass
class AnalysisDiagnostics:
    fetch_ms: float = 0.0
    indicators_ms: float = 0.0
    levels_ms: float = 0.0
    setup_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: tuple[str, ...] = ()


@dataclass
class AnalysisResult:
    setup: Setup
    overlays: dict[str, Any]
    diagnostics: AnalysisDiagnostics = field(default_factory=AnalysisDiagnostics)
    last_close_ms: int = 0
    chart_analysis: Any = None


def _as_of_from_df(df: pd.DataFrame) -> datetime:
    if df.empty:
        return datetime.fromtimestamp(binance_server_time_ms() / 1000.0, tz=UTC)
    ct = df["close_time"].iloc[-1]
    ms = int(ct)
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _fmt_zone_edge(price: float, prec: int) -> str:
    return f"{price:,.{prec}f}"


def _zone_payload(
    zones: list,
    *,
    role: str,
    prec: int,
) -> list[dict[str, Any]]:
    """Up to 3 zones, one label per unique near edge (R/S price × touches)."""
    out: list[dict[str, Any]] = []
    seen_edges: set[float] = set()
    color = (
        "rgba(14,203,129,0.22)" if role == "support" else "rgba(246,70,93,0.22)"
    )
    for z in zones:
        if role == "support":
            near = float(z.price_high)
            prefix = "S"
        else:
            near = float(z.price_low)
            prefix = "R"
        edge_key = round(near, prec)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        out.append(
            {
                "from": float(z.price_low),
                "to": float(z.price_high),
                "near": near,
                "color": color,
                "label": f"{prefix} {_fmt_zone_edge(near, prec)} ×{z.touches}",
            }
        )
    return out


def _build_chart_overlays(
    ltf: pd.DataFrame,
    setup: Setup,
    as_of: datetime,
    symbol: str,
    toggles: dict[str, bool] | None = None,
) -> dict[str, Any]:
    from core.indicators import add_all_indicators
    from core.live_chart import merge_overlays

    toggles = toggles or {}
    enriched = add_all_indicators(ltf)
    row = enriched.iloc[-1]
    atr = float(row["atr_14"])
    price = float(row["close"])
    swings, zones = structure_for_symbol(enriched, as_of, atr, None)
    swings = swings_confirmed_as_of(find_swings(enriched), as_of)

    zone_payload: list[dict[str, Any]] = []
    if toggles.get("zones", True):
        below, above = nearest_zones(zones, price, 3)
        prec = price_precision(symbol)
        zone_payload.extend(_zone_payload(below, role="support", prec=prec))
        zone_payload.extend(_zone_payload(above, role="resistance", prec=prec))

    markers: list[dict[str, Any]] = []
    if toggles.get("swings", True):
        for s in swings[-12:]:
            ts = s.pivot_time
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            sec = int(ts.timestamp())
            if s.kind == "high":
                markers.append(
                    {
                        "time": sec,
                        "position": "aboveBar",
                        "shape": "arrowDown",
                        "color": "#f6465d",
                        "text": "H",
                    }
                )
            else:
                markers.append(
                    {
                        "time": sec,
                        "position": "belowBar",
                        "shape": "arrowUp",
                        "color": "#0ecb81",
                        "text": "L",
                    }
                )

    # Phase 4: no automatic entry/SL/TP overlays — zones/swings/EMAs/VWAP only.
    return merge_overlays(setup=None, zones=zone_payload, markers=markers)


def run_analysis(
    display_symbol: str,
    timeframe: str,
    quote_volume_24h: float,
    *,
    toggles: dict[str, bool] | None = None,
) -> AnalysisResult:
    """Fetch candles, build setup, prepare chart overlays."""
    from core.candle_store import get_many
    from core.indicators import add_all_indicators
    from core.market_analysis import build_chart_analysis
    from core.models import no_trade
    from core.pattern_stats import strategy_warning
    from core.setup_builder import build_setup
    from core.symbol_ranking import display_to_rest

    rest = display_to_rest(display_symbol)
    ok, msg = validate_symbol_rest(rest)
    if not ok:
        as_of = datetime.now(UTC)
        nt = no_trade(display_symbol, timeframe, (f"✖ {msg}",), as_of)
        return AnalysisResult(nt, {}, AnalysisDiagnostics(errors=(rest,)))

    diag = AnalysisDiagnostics()
    t0 = time.perf_counter()
    htf_tfs = HIGHER_TIMEFRAMES.get(timeframe, ())
    all_tfs = (timeframe, *htf_tfs, "1d")

    try:
        frames = get_many(rest, all_tfs)
    except Exception as exc:  # noqa: BLE001 — surface to UI
        from core.models import no_trade

        as_of = datetime.now(UTC)
        nt = no_trade(display_symbol, timeframe, (f"✖ Data fetch failed: {exc}",), as_of)
        return AnalysisResult(nt, {}, AnalysisDiagnostics(errors=(str(exc),)))

    diag.fetch_ms = (time.perf_counter() - t0) * 1000.0
    for tf, fr in frames.items():
        if fr.stale:
            return AnalysisResult(
                no_trade(display_symbol, timeframe, (f"✖ Stale market data ({tf})",), datetime.now(UTC)),
                {},
                diag,
            )
        if fr.from_cache:
            diag.cache_hits += 1
        else:
            diag.cache_misses += 1

    ltf_res = frames.get(timeframe)
    if ltf_res is None or ltf_res.df.empty:
        from core.models import no_trade

        as_of = datetime.now(UTC)
        nt = no_trade(display_symbol, timeframe, ("✖ No LTF candles",), as_of)
        return AnalysisResult(nt, {}, diag)

    ltf_df = ltf_res.df
    last_close_ms = int(ltf_df["close_time"].iloc[-1])
    as_of = _as_of_from_df(ltf_df)

    t1 = time.perf_counter()
    add_all_indicators(ltf_df)
    diag.indicators_ms = (time.perf_counter() - t1) * 1000.0

    t2 = time.perf_counter()
    htf_dfs = {tf: frames[tf].df for tf in htf_tfs if tf in frames}
    daily_df = frames.get("1d").df if frames.get("1d") else None
    diag.levels_ms = (time.perf_counter() - t2) * 1000.0

    t3 = time.perf_counter()
    tick = float(tick_size(rest))
    setup = build_setup(
        rest,
        timeframe,
        ltf_df,
        htf_dfs,
        daily_df,
        as_of,
        tick,
        quote_volume_24h,
    )
    diag.setup_ms = (time.perf_counter() - t3) * 1000.0

    toggles = toggles or {}
    show_patterns = bool(toggles.get("show_patterns", False))
    warn_fn = lambda strat: strategy_warning(rest, timeframe, strat)  # noqa: E731
    chart_analysis = build_chart_analysis(
        display_symbol,
        rest,
        timeframe,
        ltf_df,
        htf_dfs,
        setup,
        show_patterns=show_patterns,
        warning_for=warn_fn,
        enriched_row=ltf_df.iloc[-1],
        tick_size=tick,
    )

    overlays = _build_chart_overlays(ltf_df, setup, as_of, rest, toggles)
    return AnalysisResult(setup, overlays, diag, last_close_ms=last_close_ms, chart_analysis=chart_analysis)