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
from core.exchange_info import binance_server_time_ms, tick_size
from core.levels import find_swings, nearest_zones, structure_for_symbol, swings_confirmed_as_of
from core.models import Direction, Setup
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


def _as_of_from_df(df: pd.DataFrame) -> datetime:
    if df.empty:
        return datetime.fromtimestamp(binance_server_time_ms() / 1000.0, tz=UTC)
    ct = df["close_time"].iloc[-1]
    ms = int(ct)
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _build_chart_overlays(
    ltf: pd.DataFrame,
    setup: Setup,
    as_of: datetime,
    toggles: dict[str, bool] | None = None,
) -> dict[str, Any]:
    from core.indicators import add_all_indicators
    from core.live_chart import merge_overlays, setup_to_overlay_dict

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
        for z in below:
            zone_payload.append(
                {
                    "from": z.price_low,
                    "to": z.price_high,
                    "color": "rgba(14,203,129,0.35)",
                    "label": f"Support ({z.touches})",
                }
            )
        for z in above:
            zone_payload.append(
                {
                    "from": z.price_low,
                    "to": z.price_high,
                    "color": "rgba(246,70,93,0.35)",
                    "label": f"Resistance ({z.touches})",
                }
            )

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

    if setup.direction != Direction.NO_TRADE and toggles.get("setup_lines", True):
        sig_ts = setup.signal_candle_time
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.replace(tzinfo=UTC)
        sec = int(sig_ts.timestamp())
        markers.append(
            {
                "time": sec,
                "position": "aboveBar" if setup.direction == Direction.LONG else "belowBar",
                "shape": "arrowUp" if setup.direction == Direction.LONG else "arrowDown",
                "color": "#2962FF",
                "text": "Signal",
            }
        )

    setup_dict = setup_to_overlay_dict(setup) if toggles.get("setup_lines", True) else None
    return merge_overlays(setup=setup if setup_dict else None, zones=zone_payload, markers=markers)


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
    from core.models import no_trade
    from core.setup_builder import build_setup
    from core.storage import save_setup
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

    if setup.direction != Direction.NO_TRADE:
        save_setup(setup)

    overlays = _build_chart_overlays(ltf_df, setup, as_of, toggles)
    return AnalysisResult(setup, overlays, diag, last_close_ms=last_close_ms)