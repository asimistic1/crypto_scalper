"""
Crypto Scalper — Phase 1: live chart dashboard (Streamlit).
Run with: streamlit run app.py  (inside activated venv)
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from core.chart import build_chart
from core.data import (
    display_to_ccxt_symbol,
    get_candles,
    get_exchange,
    get_ticker,
    get_top_symbols,
)
from core.indicators import add_basic_indicators, add_emas

PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

FALLBACK_COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"]

st.set_page_config(page_title="Crypto Scalper", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Crypto Scalper")
st.caption("Live Binance USDT-M futures chart — Phase 1")


@st.cache_resource
def cached_exchange():
    """One ccxt client per Streamlit session (rate limit friendly)."""
    return get_exchange()


@st.cache_data(ttl=20, show_spinner=False)
def load_candle_data(ccxt_symbol: str, timeframe: str, limit: int):
    """Cached OHLCV + indicators; TTL keeps auto-refresh fast."""
    df, err = get_candles(ccxt_symbol, timeframe, limit)
    if err or df is None:
        return None, err
    df = add_emas(df)
    df = add_basic_indicators(df)
    return df, None


def format_volume(vol: float) -> str:
    """Human-readable volume like 1.2B / 350M."""
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return f"{vol:.2f}"


def metric_number(val) -> str:
    """Format a numeric indicator for the metric cards, or dash if missing."""
    if val is None or (isinstance(val, float) and (math.isnan(val) or pd.isna(val))):
        return "—"
    return f"{float(val):.2f}"


_ = cached_exchange()

with st.sidebar:
    st.header("Settings")

    symbols, sym_err = get_top_symbols(30)
    if sym_err:
        st.warning(sym_err)
    if not symbols:
        symbols = FALLBACK_COINS

    default_idx = symbols.index("BTC/USDT") if "BTC/USDT" in symbols else 0
    display_symbol = st.selectbox("Coin", symbols, index=default_idx)
    ccxt_symbol = display_to_ccxt_symbol(display_symbol)

    timeframe = st.radio("Timeframe", ["5m", "15m", "1h"], index=1, horizontal=True)
    candle_limit = st.slider("Number of candles", min_value=100, max_value=1000, value=300, step=50)

    auto_refresh = st.toggle("Auto-refresh", value=True)
    interval_labels = {"30s": 30_000, "60s": 60_000, "120s": 120_000}
    refresh_label = st.selectbox("Refresh interval", list(interval_labels.keys()), index=1)
    refresh_ms = interval_labels[refresh_label]

    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)

if auto_refresh:
    st_autorefresh(interval=refresh_ms, key="price_autorefresh")

if analyze_clicked:
    load_candle_data.clear()

df, candle_err = load_candle_data(ccxt_symbol, timeframe, candle_limit)

if candle_err:
    st.error(candle_err)
    st.stop()

if df is None or df.empty:
    st.error("No chart data available.")
    st.stop()

ticker, ticker_err = get_ticker(ccxt_symbol)
if ticker_err:
    st.warning(ticker_err)
    ticker = {}

last_row = df.iloc[-1]
price = float(ticker.get("last") or last_row["close"])
change_pct = float(ticker.get("change_pct", 0))
rsi_val = last_row.get("rsi_14")
atr_val = last_row.get("atr_14")
atr_pct = (float(atr_val) / price * 100) if atr_val and price and not pd.isna(atr_val) else 0.0

m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric("Current Price", f"{price:,.4f}")
m2.metric("24h Change %", f"{change_pct:+.2f}%")
m3.metric("24h High", f"{ticker.get('high_24h', 0):,.4f}")
m4.metric("24h Low", f"{ticker.get('low_24h', 0):,.4f}")
m5.metric("24h Volume", format_volume(float(ticker.get("quote_volume_24h", 0))))
m6.metric("RSI (14)", metric_number(rsi_val))
m7.metric("ATR (14) %", f"{atr_pct:.2f}%" if atr_pct else "—")

chart_col, setup_col = st.columns([3, 1])

with chart_col:
    fig = build_chart(df, ccxt_symbol, timeframe)
    st.plotly_chart(fig, use_container_width=True)

with setup_col:
    st.subheader("Trade Setup")
    st.info("Setup analysis coming in Phase 2.")

# is_closed=False means the current candle is still printing
still_forming = "yes" if not bool(last_row.get("is_closed", True)) else "no"
updated = datetime.now(PAKISTAN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
st.caption(
    f"Data: Binance USDT-M Futures • Last updated: {updated} • "
    f"Last candle still forming: {still_forming}"
)