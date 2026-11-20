"""
Legacy Plotly chart (Phase 1). Superseded by components/live_chart (WebSocket + Lightweight Charts).
Kept for reference only — not used by streamlit_app.py.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_chart(df: pd.DataFrame, symbol: str, timeframe: str) -> go.Figure:
    """Deprecated: use the browser live chart component instead."""
    up = df["close"] >= df["open"]
    colors = ["#26a69a" if u else "#ef5350" for u in up]
    current_price = float(df["close"].iloc[-1])
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25]
    )
    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=df["time"], y=df["volume"], marker_color=colors, showlegend=False),
        row=2,
        col=1,
    )
    fig.add_hline(y=current_price, line_dash="dash", row=1, col=1)
    title_symbol = symbol.split(":")[0]
    fig.update_layout(template="plotly_dark", title=f"{title_symbol} · {timeframe}", height=750)
    return fig