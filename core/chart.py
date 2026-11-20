"""
Build the main Plotly candlestick + volume chart with EMA overlays.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_chart(df: pd.DataFrame, symbol: str, timeframe: str) -> go.Figure:
    """
    Two-row chart: candles (~75% height) and volume (~25%), dark theme.
    EMA colors: 9 yellow, 21 orange, 50 blue, 200 purple.
    """
    # Candle direction for colors (green up, red down)
    up = df["close"] >= df["open"]
    colors = ["#26a69a" if u else "#ef5350" for u in up]

    # Current price from last close (includes live forming candle)
    current_price = float(df["close"].iloc[-1])

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#26a69a",
            increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350",
            decreasing_fillcolor="#ef5350",
        ),
        row=1,
        col=1,
    )

    ema_styles = [
        ("ema_9", "#FFEB3B", "EMA 9"),
        ("ema_21", "#FF9800", "EMA 21"),
        ("ema_50", "#2196F3", "EMA 50"),
        ("ema_200", "#9C27B0", "EMA 200"),
    ]
    for col_name, color, label in ema_styles:
        if col_name in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df["time"],
                    y=df[col_name],
                    mode="lines",
                    name=label,
                    line=dict(color=color, width=1),
                ),
                row=1,
                col=1,
            )

    fig.add_trace(
        go.Bar(
            x=df["time"],
            y=df["volume"],
            name="Volume",
            marker_color=colors,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Horizontal dashed line at last price
    fig.add_hline(
        y=current_price,
        line_dash="dash",
        line_color="#B0BEC5",
        annotation_text=f" {current_price:,.4f}",
        annotation_position="right",
        row=1,
        col=1,
    )

    title_symbol = symbol.split(":")[0]
    fig.update_layout(
        template="plotly_dark",
        title=f"{title_symbol} · {timeframe}",
        height=750,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=80, t=60, b=40),
    )

    # Pakistan time on x-axis; hide gaps between candles
    fig.update_xaxes(
        type="date",
        tickformat="%d %b %H:%M",
        showgrid=True,
        gridcolor="#37474F",
        row=2,
        col=1,
    )
    fig.update_xaxes(type="date", row=1, col=1, showticklabels=False)
    fig.update_yaxes(title_text="Price", row=1, col=1, gridcolor="#37474F")
    fig.update_yaxes(title_text="Vol", row=2, col=1, gridcolor="#37474F")

    return fig