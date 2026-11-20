"""
Bidirectional Streamlit custom component — live Binance WebSocket chart.

Uses declare_component so symbol/timeframe/overlays update without iframe reload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit.components.v1 as components

from core.data import symbol_to_rest_id
from core.models import Setup

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "components" / "live_chart" / "frontend"
_LIVE_CHART = components.declare_component("live_chart", path=str(_FRONTEND_DIR))

# Stable iframe identity — do not change per rerun
_COMPONENT_KEY = "live_chart"


def _df_to_candle_payload(df: pd.DataFrame | None) -> list[dict[str, float | int]]:
    if df is None or df.empty:
        return []
    rows: list[dict[str, float | int]] = []
    for _, row in df.iterrows():
        ts = row["time"]
        sec = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
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


def setup_to_overlay_dict(setup: Setup | None) -> dict[str, Any] | None:
    """Map Setup dataclass → browser overlay payload."""
    if setup is None or setup.direction.value == "NO_TRADE":
        return None
    return {
        "direction": setup.direction.value,
        "entry": setup.entry,
        "sl": setup.stop_loss,
        "tp1": setup.tp1,
        "tp2": setup.tp2,
        "tp3": setup.tp3,
        "status": setup.status.value,
        "setup_id": setup.setup_id,
        "expires_at": setup.expires_at.isoformat() if setup.expires_at else None,
        "signal_time": setup.signal_candle_time.isoformat(),
    }


def merge_overlays(
    *,
    setup: Setup | None = None,
    lines: list[dict[str, Any]] | None = None,
    zones: list[dict[str, Any]] | None = None,
    markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "setup": setup_to_overlay_dict(setup),
        "lines": lines or [],
        "zones": zones or [],
        "markers": markers or [],
    }


def render_live_chart(
    symbol: str,
    timeframe: str,
    *,
    overlays: dict[str, Any] | None = None,
    height: int = 750,
    fallback_candles: pd.DataFrame | None = None,
    history_limit: int = 1000,
    streaming_enabled: bool = True,
    tick_size: float = 0.0,
    toggles: dict[str, bool] | None = None,
) -> Any:
    """
    Render the chart component (constant key — WS stays connected).
    Returns component events from the browser (candle_closed / status_changed), or None.
    """
    rest = symbol_to_rest_id(symbol)
    display = symbol.split(":")[0] if ":" in symbol else symbol
    default_toggles = {
        "zones": True,
        "swings": True,
        "emas": True,
        "vwap": False,
        "setup_lines": True,
    }
    if toggles:
        default_toggles.update(toggles)

    return _LIVE_CHART(
        symbol=rest,
        display_symbol=display,
        timeframe=timeframe,
        tick_size=float(tick_size),
        height=int(height),
        history_limit=min(int(history_limit), 1000),
        streaming_enabled=bool(streaming_enabled),
        fallback_candles=_df_to_candle_payload(fallback_candles),
        overlays=overlays or {},
        toggles=default_toggles,
        theme="dark",
        key=_COMPONENT_KEY,
        default=None,
    )


def render_live_chart_legacy_html(*_args: Any, **_kwargs: Any) -> None:
    """Deprecated — Phase 2 uses declare_component (no st.components.v1.html)."""
    raise RuntimeError("Use render_live_chart() — live_chart.html iframe path was removed in Step 8.")