"""
Top USDT perpetual symbols by 24h quote volume (REST only, no ccxt).
"""

from __future__ import annotations

from core.exchange_info import refresh_exchange_info
from core.http_client import fapi_get


def rest_to_display(rest_symbol: str) -> str:
    if rest_symbol.endswith("USDT"):
        base = rest_symbol[:-4]
        return f"{base}/USDT"
    return rest_symbol


def display_to_rest(display: str) -> str:
    return display.replace("/", "").upper()


def fetch_top_symbols_by_volume(limit: int = 30) -> tuple[tuple[str, ...], dict[str, float]]:
    """
    Returns (display symbols e.g. BTC/USDT, quote_volume map keyed by REST id).
    """
    trading = refresh_exchange_info()
    payload = fapi_get("/fapi/v1/ticker/24hr").json()
    ranked: list[tuple[float, str]] = []
    volumes: dict[str, float] = {}
    for row in payload:
        sym = str(row.get("symbol", "")).upper()
        if sym not in trading or trading[sym].get("status") != "TRADING":
            continue
        qv = float(row.get("quoteVolume") or 0.0)
        volumes[sym] = qv
        ranked.append((qv, sym))
    ranked.sort(key=lambda x: x[0], reverse=True)
    top = tuple(rest_to_display(sym) for _, sym in ranked[:limit])
    return top, volumes