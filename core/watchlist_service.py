"""Watchlist metrics — server-side on closed candles."""

from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd

from core.candle_store import get_closed_candles
from core.http_client import fapi_get
from core.indicators import add_all_indicators
from core.levels import nearest_zones, structure_for_symbol
from core.rate_limit import BinanceCooldownActive
from core.trend import get_trend

_funding_cache: dict[str, float] = {}
_funding_at: float = 0.0


def _funding_rates() -> dict[str, float]:
    global _funding_at
    if time.time() - _funding_at < 60 and _funding_cache:
        return _funding_cache
    try:
        data = fapi_get("/fapi/v1/premiumIndex").json()
        out = {row["symbol"]: float(row.get("lastFundingRate", 0)) for row in data}
        _funding_cache.clear()
        _funding_cache.update(out)
        _funding_at = time.time()
        return out
    except Exception:
        return _funding_cache


@dataclass
class WatchRow:
    symbol: str
    display: str
    price: float
    change_24h_pct: float
    volume_quote: float
    trend_15m: str
    trend_1h: str
    trend_4h: str
    dist_support_pct: float | None
    dist_resistance_pct: float | None
    dist_support_atr: float | None
    atr_pct: float
    rsi: float | None
    funding: float | None
    aligned: bool
    near_zone: bool


def _trend_label(df: pd.DataFrame) -> str:
    if df.empty:
        return "neutral"
    as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True)
    tr = get_trend(df, as_of.to_pydatetime())
    return tr.bias.value


def build_watch_row(symbol_rest: str) -> WatchRow | None:
    try:
        c15 = get_closed_candles(symbol_rest, "15m", full=True).df
        c1h = get_closed_candles(symbol_rest, "1h", full=True).df
        c4h = get_closed_candles(symbol_rest, "4h", full=True).df
    except BinanceCooldownActive:
        return None
    except Exception:
        return None
    if c15.empty:
        return None
    add_all_indicators(c15)
    row = c15.iloc[-1]
    price = float(row["close"])
    atr = float(row.get("atr_14") or 0)
    atr_pct = 100.0 * atr / price if price else 0.0
    rsi = float(row["rsi_14"]) if pd.notna(row.get("rsi_14")) else None
    chg = 0.0
    if len(c15) > 96:
        chg = 100.0 * (price / float(c15.iloc[-96]["close"]) - 1.0)
    vol = float(c15["quote_volume"].tail(96).sum())
    _, zones = structure_for_symbol(c15, pd.Timestamp.utcnow(), atr, None)
    below, above = nearest_zones(zones, price, 1)
    ds = 100.0 * abs(price - below[0].price_high) / price if below else None
    dr = 100.0 * abs(price - above[0].price_low) / price if above else None
    ds_atr = (abs(price - below[0].price_high) / atr) if below and atr else None
    t15 = _trend_label(c15)
    t1 = _trend_label(add_all_indicators(c1h.copy()) if not c1h.empty else c1h)
    t4 = _trend_label(add_all_indicators(c4h.copy()) if not c4h.empty else c4h)
    aligned = t15 == t1 == t4 and t15 in ("bullish", "bearish")
    near = ds_atr is not None and ds_atr < 0.5
    fund = _funding_rates().get(symbol_rest)
    disp = symbol_rest.replace("USDT", "/USDT")
    return WatchRow(
        symbol=symbol_rest,
        display=disp,
        price=price,
        change_24h_pct=chg,
        volume_quote=vol,
        trend_15m=t15,
        trend_1h=t1,
        trend_4h=t4,
        dist_support_pct=ds,
        dist_resistance_pct=dr,
        dist_support_atr=ds_atr,
        atr_pct=atr_pct,
        rsi=rsi,
        funding=fund,
        aligned=aligned,
        near_zone=near,
    )