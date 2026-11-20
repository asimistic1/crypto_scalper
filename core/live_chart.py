"""
Embed the browser-side Binance WebSocket chart (TradingView Lightweight Charts v5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from core.data import symbol_to_rest_id

_COMPONENT_HTML = (
    Path(__file__).resolve().parent.parent / "components" / "live_chart" / "live_chart.html"
)


def _df_to_candle_payload(df: pd.DataFrame) -> list[dict[str, float | int]]:
    """OHLCV list for the browser (UTC seconds for Lightweight Charts)."""
    rows: list[dict[str, float | int]] = []
    for _, row in df.iterrows():
        ts = row["time"]
        if hasattr(ts, "timestamp"):
            sec = int(ts.timestamp())
        else:
            sec = int(pd.Timestamp(ts).timestamp())
        rows.append(
            {
                "time": sec,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return rows


def build_chart_html(
    symbol: str,
    timeframe: str,
    *,
    overlays: dict[str, Any] | None = None,
    height: int = 750,
    fallback_candles: list[dict[str, Any]] | None = None,
    history_limit: int = 1000,
    streaming_enabled: bool = True,
) -> str:
    """Inject JSON config into the static HTML shell (stable except when params change)."""
    template = _COMPONENT_HTML.read_text(encoding="utf-8")
    rest = symbol_to_rest_id(symbol)
    display = symbol.split(":")[0] if ":" in symbol else symbol

    config = {
        "restSymbol": rest,
        "wsSymbol": rest.lower(),
        "timeframe": timeframe,
        "displaySymbol": display,
        "height": height,
        "overlays": overlays or {},
        "fallbackCandles": fallback_candles or [],
        "historyLimit": min(int(history_limit), 1000),
        "streamingEnabled": streaming_enabled,
    }
    safe_json = json.dumps(config).replace("</", "<\\/")
    return template.replace("/*__INJECT_CONFIG__*/", f"window.__CHART_CONFIG__ = {safe_json};")


def render_live_chart(
    symbol: str,
    timeframe: str,
    overlays: dict[str, Any] | None = None,
    height: int = 750,
    fallback_candles: pd.DataFrame | None = None,
    history_limit: int = 1000,
    streaming_enabled: bool = True,
) -> None:
    """
    Render the live WebSocket chart iframe.
    Only rebuilds HTML when symbol, timeframe, overlays, or height change (avoids WS reset).
    """
    fb = _df_to_candle_payload(fallback_candles) if fallback_candles is not None else None
    # Key excludes volatile overlay prices so tiny price moves do not reset the WebSocket iframe.
    overlay_sig = json.dumps(overlays or {}, sort_keys=True, default=str)
    cache_payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "overlay_sig": overlay_sig,
        "height": height,
        "history_limit": history_limit,
        "streaming_enabled": streaming_enabled,
    }
    config_key = hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode()).hexdigest()

    if st.session_state.get("live_chart_key") != config_key:
        st.session_state["live_chart_key"] = config_key
        st.session_state["live_chart_html"] = build_chart_html(
            symbol,
            timeframe,
            overlays=overlays,
            height=height,
            fallback_candles=fb,
            history_limit=history_limit,
            streaming_enabled=streaming_enabled,
        )

    html = st.session_state.get("live_chart_html", "")
    # Extra padding for header + status row inside the component
    st.components.v1.html(html, height=height + 100, scrolling=False)