"""
Crypto Scalper — Phase 1: live chart dashboard (Streamlit).
Run with: streamlit run streamlit_app.py  (inside activated venv)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core.chart import build_chart
from core.chart_store import get as get_stored_chart, save as save_stored_chart
from core.rate_limit import BinanceCooldownActive, banner_message, is_in_cooldown

from core.data import (
    TOP_SYMBOLS_FALLBACK,
    DataFetchError,
    bind_exchange,
    configure_network,
    create_binance_exchange,
    display_to_ccxt_symbol,
    fetch_ohlcv_dataframe,
    fetch_ticker_dict,
    fetch_top_symbols_list,
    is_rate_limit_message,
    load_proxy_from_env,
    region_block_help_markdown,
    region_block_user_message,
    use_lightweight_binance,
)
from core.indicators import add_basic_indicators, add_emas
PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

st.set_page_config(page_title="Crypto Scalper", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _resolve_binance_proxy() -> str | None:
    proxy = load_proxy_from_env()
    for key in ("BINANCE_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        try:
            if key in st.secrets and str(st.secrets[key]).strip():
                proxy = str(st.secrets[key]).strip()
                break
        except (FileNotFoundError, KeyError):
            pass
    return proxy


configure_network(_resolve_binance_proxy())
_PROXY_KEY = _resolve_binance_proxy() or ""
_LIGHTWEIGHT = use_lightweight_binance()

if not _LIGHTWEIGHT:

    @st.cache_resource(show_spinner=False)
    def cached_binance_exchange(proxy_key: str):
        return create_binance_exchange(proxy_key or None)

    bind_exchange(cached_binance_exchange(_PROXY_KEY))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_top_symbols(n: int, fetch_volume_ranking: bool) -> tuple[str, ...]:
    return tuple(fetch_top_symbols_list(n, fetch_volume_ranking=fetch_volume_ranking))


@st.cache_data(ttl=5, show_spinner=False)
def cached_ticker_dict(ccxt_symbol: str) -> dict:
    return fetch_ticker_dict(ccxt_symbol)


@st.cache_data(ttl=30, show_spinner=False)
def cached_ohlcv_df(ccxt_symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    return fetch_ohlcv_dataframe(ccxt_symbol, timeframe, limit)


def _load_chart_df(ccxt_symbol: str, timeframe: str, limit: int) -> tuple[pd.DataFrame | None, str | None, bool]:
    """
    Returns (df, error_message, used_stale).
    During cooldown: no Binance requests; stale only if key matches.
    """
    key = (ccxt_symbol, timeframe, limit)
    if is_in_cooldown():
        stale_df, saved_at = get_stored_chart(ccxt_symbol, timeframe, limit)
        if stale_df is not None and saved_at is not None:
            label = saved_at.strftime("%H:%M:%S")
            return stale_df, f"Showing cached data from {label}", True
        return None, banner_message(), False

    try:
        raw = cached_ohlcv_df(ccxt_symbol, timeframe, limit)
        df = add_basic_indicators(add_emas(raw))
        save_stored_chart(ccxt_symbol, timeframe, limit, df)
        return df, None, False
    except BinanceCooldownActive:
        stale_df, saved_at = get_stored_chart(ccxt_symbol, timeframe, limit)
        if stale_df is not None and saved_at is not None:
            label = saved_at.strftime("%H:%M:%S")
            return stale_df, f"Showing cached data from {label}", True
        return None, banner_message(), False
    except DataFetchError as e:
        if e.http_code in (418, 429):
            stale_df, saved_at = get_stored_chart(ccxt_symbol, timeframe, limit)
            if stale_df is not None and saved_at is not None:
                label = saved_at.strftime("%H:%M:%S")
                return stale_df, f"Showing cached data from {label}", True
            return None, banner_message(), False
        return None, e.message, False


def _fetch_ticker_safe(ccxt_symbol: str) -> tuple[dict | None, str | None]:
    if is_in_cooldown():
        cached = st.session_state.get("last_ticker", {}).get(ccxt_symbol)
        return cached, None
    try:
        t = cached_ticker_dict(ccxt_symbol)
        st.session_state.setdefault("last_ticker", {})[ccxt_symbol] = t
        return t, None
    except BinanceCooldownActive:
        cached = st.session_state.get("last_ticker", {}).get(ccxt_symbol)
        return cached, None
    except DataFetchError as e:
        if e.http_code in (418, 429):
            cached = st.session_state.get("last_ticker", {}).get(ccxt_symbol)
            return cached, None
        return None, e.message


def format_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return f"{vol:.2f}"


def metric_number(val) -> str:
    if val is None or (isinstance(val, float) and (math.isnan(val) or pd.isna(val))):
        return "—"
    return f"{float(val):.2f}"


def _format_price(ticker: dict | None, last_close: float) -> tuple[str, bool]:
    """Return (label, from_candle)."""
    if ticker and ticker.get("last"):
        return f"{float(ticker['last']):,.4f}", False
    return f"{last_close:,.4f} (from last candle)", True


st.title("Crypto Scalper")
_mode = "lightweight REST (cloud)" if _LIGHTWEIGHT else "ccxt"
st.caption(f"Live Binance USDT-M futures chart — Phase 1 • data mode: {_mode}")

if is_in_cooldown():
    st.warning(f"⏳ {banner_message()}")

# --- Sidebar (full page rerun only) ---
with st.sidebar:
    st.header("Settings")

    if "fetch_coin_ranking" not in st.session_state:
        st.session_state["fetch_coin_ranking"] = False

    if st.button("Load top 30 by volume (heavy API)", use_container_width=True):
        st.session_state["fetch_coin_ranking"] = True
        cached_top_symbols.clear()

    try:
        symbols = list(cached_top_symbols(30, st.session_state["fetch_coin_ranking"]))
        sym_err = None
    except (DataFetchError, BinanceCooldownActive) as e:
        symbols = list(TOP_SYMBOLS_FALLBACK)
        sym_err = getattr(e, "message", str(e))
        if isinstance(e, BinanceCooldownActive):
            sym_err = banner_message()

    if sym_err and sym_err != banner_message():
        st.warning(sym_err)
        if sym_err == region_block_user_message():
            with st.expander("Why is Binance blocked?"):
                st.markdown(region_block_help_markdown())

    if not symbols:
        symbols = list(TOP_SYMBOLS_FALLBACK)

    default_idx = symbols.index("BTC/USDT") if "BTC/USDT" in symbols else 0
    display_symbol = st.selectbox("Coin", symbols, index=default_idx)
    ccxt_symbol = display_to_ccxt_symbol(display_symbol)

    timeframe = st.radio("Timeframe", ["5m", "15m", "1h"], index=1, horizontal=True)
    candle_limit = st.slider("Number of candles", min_value=100, max_value=1000, value=300, step=50)

    auto_refresh = st.toggle(
        "Auto-refresh",
        value=True,
        help="Price every 10s, chart every 60s. Turn off to pause API polling.",
    )

    if st.button("Analyze", type="primary", use_container_width=True):
        cached_ohlcv_df.clear()
        cached_ticker_dict.clear()

# Persist selections for fragments
st.session_state["ccxt_symbol"] = ccxt_symbol
st.session_state["timeframe"] = timeframe
st.session_state["candle_limit"] = candle_limit
st.session_state["auto_refresh"] = auto_refresh


def render_price_metrics() -> None:
    """Top metric row — only /fapi/v1/ticker/24hr (weight 1)."""
    sym = st.session_state["ccxt_symbol"]
    tf = st.session_state["timeframe"]
    lim = st.session_state["candle_limit"]

    stale_df, saved_at = get_stored_chart(sym, tf, lim)
    last_close = float(stale_df.iloc[-1]["close"]) if stale_df is not None else 0.0

    ticker, _ = _fetch_ticker_safe(sym)
    if last_close:
        price_label, _ = _format_price(ticker, last_close)
    elif ticker and ticker.get("last"):
        price_label = f"{float(ticker['last']):,.4f}"
    else:
        price_label = "—"

    if saved_at and is_in_cooldown():
        st.caption(f"Showing cached data from {saved_at.strftime('%H:%M:%S')}")

    has_ticker = ticker is not None
    change = f"{ticker['change_pct']:+.2f}%" if has_ticker else "—"
    high = f"{ticker['high_24h']:,.4f}" if has_ticker else "—"
    low = f"{ticker['low_24h']:,.4f}" if has_ticker else "—"
    vol = format_volume(float(ticker["quote_volume_24h"])) if has_ticker else "—"

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Current Price", price_label)
    m2.metric("24h Change %", change)
    m3.metric("24h High", high)
    m4.metric("24h Low", low)
    m5.metric("24h Volume", vol)


def render_chart_block() -> None:
    """Candles, indicators, and chart (heavier klines call)."""
    sym = st.session_state["ccxt_symbol"]
    tf = st.session_state["timeframe"]
    lim = st.session_state["candle_limit"]

    df, stale_msg, _ = _load_chart_df(sym, tf, lim)
    if df is None or df.empty:
        st.error(stale_msg or "No chart data available.")
        return

    if stale_msg:
        st.caption(stale_msg)

    last_row = df.iloc[-1]
    rsi_val = last_row.get("rsi_14")
    atr_val = last_row.get("atr_14")
    price = float(last_row["close"])
    atr_pct = (float(atr_val) / price * 100) if atr_val and not pd.isna(atr_val) else None

    m6, m7 = st.columns(2)
    m6.metric("RSI (14)", metric_number(rsi_val))
    m7.metric("ATR (14) %", f"{atr_pct:.2f}%" if atr_pct is not None else "—")

    chart_col, setup_col = st.columns([3, 1])
    with chart_col:
        fig = build_chart(df, sym, tf)
        st.plotly_chart(fig, use_container_width=True, key=f"chart-{sym}-{tf}-{lim}")
    with setup_col:
        st.subheader("Trade Setup")
        st.info("Setup analysis coming in Phase 2.")

    still_forming = "yes" if not bool(last_row.get("is_closed", True)) else "no"
    updated = datetime.now(PAKISTAN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    st.caption(
        f"Data: Binance USDT-M Futures • Last updated: {updated} • "
        f"Last candle still forming: {still_forming}"
    )


def _invoke_fragment(callback, run_every: timedelta | None) -> None:
    """Wrap callback in st.fragment with optional run_every polling."""
    if run_every is not None:
        st.fragment(run_every=run_every)(callback)()
    else:
        st.fragment(callback)()


_price_every = timedelta(seconds=10) if st.session_state.get("auto_refresh", True) else None
_chart_every = timedelta(seconds=60) if st.session_state.get("auto_refresh", True) else None

_invoke_fragment(render_price_metrics, _price_every)
_invoke_fragment(render_chart_block, _chart_every)