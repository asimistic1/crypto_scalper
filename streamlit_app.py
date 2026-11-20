"""
Crypto Scalper — Phase 1: live chart dashboard (Streamlit).
Run with: streamlit run streamlit_app.py  (inside activated venv)
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from core.chart import build_chart
from core.data import (
    TOP_SYMBOLS_FALLBACK,
    bind_exchange,
    configure_network,
    create_binance_exchange,
    display_to_ccxt_symbol,
    get_candles,
    get_ticker,
    get_top_symbols,
    is_rate_limit_message,
    load_proxy_from_env,
    region_block_help_markdown,
    region_block_user_message,
    use_lightweight_binance,
)
from core.indicators import add_basic_indicators, add_emas

PAKISTAN_TZ = ZoneInfo("Asia/Karachi")
RATE_LIMIT_COOLDOWN_SEC = 60

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
    """Secrets (cloud) override .env (local). Credentials stay out of logs."""
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

# ccxt + load_markets() is skipped on Render — avoids the heaviest REST burst.
if not _LIGHTWEIGHT:


    @st.cache_resource(show_spinner=False)
    def cached_binance_exchange(proxy_key: str):
        return create_binance_exchange(proxy_key or None)

    bind_exchange(cached_binance_exchange(_PROXY_KEY))

_OHLCV_TTL = 30 if _LIGHTWEIGHT else 15

st.title("Crypto Scalper")
_mode = "lightweight REST (cloud)" if _LIGHTWEIGHT else "ccxt"
st.caption(f"Live Binance USDT-M futures chart — Phase 1 • data mode: {_mode}")


def _show_region_block_help(err: str | None) -> None:
    if not err or err != region_block_user_message():
        return
    with st.expander("Why is Binance blocked on Streamlit Cloud?"):
        st.markdown(region_block_help_markdown())


def _mark_rate_limited() -> None:
    st.session_state["rate_limit_until"] = time.time() + RATE_LIMIT_COOLDOWN_SEC


def _clear_rate_limit_if_ok(err: str | None) -> None:
    if err is None and "rate_limit_until" in st.session_state:
        del st.session_state["rate_limit_until"]


def _show_rate_limit_banner(err: str | None, *, show_stale_hint: bool = False) -> None:
    if not is_rate_limit_message(err):
        return
    _mark_rate_limited()
    until = st.session_state.get("rate_limit_until", time.time() + RATE_LIMIT_COOLDOWN_SEC)
    remaining = max(0, int(until - time.time()))
    extra = " Showing your last good chart below." if show_stale_hint else ""
    st.warning(
        f"⏳ Binance rate limit — too many requests from this server IP. "
        f"Retry in **{remaining}s** (or click **Analyze** after the countdown).{extra}"
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_top_symbols(n: int, fetch_volume_ranking: bool) -> tuple[tuple[str, ...], str | None]:
    """Top coins — on Render uses static list unless user requests ranking (heavy)."""
    symbols, err = get_top_symbols(n, fetch_volume_ranking=fetch_volume_ranking)
    return tuple(symbols), err


@st.cache_data(ttl=_OHLCV_TTL, show_spinner=False)
def cached_fetch_ohlcv(ccxt_symbol: str, timeframe: str, limit: int):
    """Raw OHLCV from Binance — short TTL so UI clicks don't spam the API."""
    return get_candles(ccxt_symbol, timeframe, limit)


@st.cache_data(ttl=_OHLCV_TTL, show_spinner=False)
def cached_ticker(ccxt_symbol: str):
    return get_ticker(ccxt_symbol)


def load_candle_data(ccxt_symbol: str, timeframe: str, limit: int):
    """Apply indicators on top of cached OHLCV (indicators are cheap CPU only)."""
    df, err = cached_fetch_ohlcv(ccxt_symbol, timeframe, limit)
    if err or df is None:
        return None, err
    df = add_emas(df)
    df = add_basic_indicators(df)
    return df, None


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


# --- Sidebar ---
with st.sidebar:
    st.header("Settings")

    if "fetch_coin_ranking" not in st.session_state:
        st.session_state["fetch_coin_ranking"] = False

    if st.button(
        "Load top 30 by volume (heavy API)",
        use_container_width=True,
        help="Skipped on cloud by default — calls fetch_tickers once per hour when enabled.",
    ):
        st.session_state["fetch_coin_ranking"] = True
        cached_top_symbols.clear()

    symbols, sym_err = cached_top_symbols(30, st.session_state["fetch_coin_ranking"])
    symbols = list(symbols)
    if sym_err and not is_rate_limit_message(sym_err):
        st.warning(sym_err)
        _show_region_block_help(sym_err)
    elif sym_err:
        st.caption(sym_err)
    if not symbols:
        symbols = list(TOP_SYMBOLS_FALLBACK)

    default_idx = symbols.index("BTC/USDT") if "BTC/USDT" in symbols else 0
    display_symbol = st.selectbox("Coin", symbols, index=default_idx)
    ccxt_symbol = display_to_ccxt_symbol(display_symbol)

    timeframe = st.radio("Timeframe", ["5m", "15m", "1h"], index=1, horizontal=True)
    candle_limit = st.slider("Number of candles", min_value=100, max_value=1000, value=300, step=50)

    # Default OFF on Render/shared IPs — user opts in to polling (min 60s).
    auto_refresh = st.toggle(
        "Auto-refresh",
        value=False,
        help="Leave off on cloud hosts to avoid Binance HTTP 418/429.",
    )
    interval_labels = {"60s": 60_000, "120s": 120_000}
    refresh_label = st.selectbox("Refresh interval", list(interval_labels.keys()), index=0)
    refresh_ms = interval_labels[refresh_label]

    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)

    if analyze_clicked:
        cached_fetch_ohlcv.clear()
        cached_ticker.clear()

if auto_refresh:
    st_autorefresh(interval=refresh_ms, key="price_autorefresh")

chart_key = (ccxt_symbol, timeframe, candle_limit)
df, candle_err = load_candle_data(ccxt_symbol, timeframe, candle_limit)

if df is not None and not candle_err:
    st.session_state["last_good_chart"] = df
    st.session_state["last_good_chart_key"] = chart_key

_clear_rate_limit_if_ok(candle_err)

if candle_err:
    if is_rate_limit_message(candle_err):
        stale = st.session_state.get("last_good_chart")
        if stale is not None:
            _show_rate_limit_banner(candle_err, show_stale_hint=True)
            df, candle_err = stale, None
        else:
            _show_rate_limit_banner(candle_err)
            st.stop()
    else:
        st.error(candle_err)
        _show_region_block_help(candle_err)
        st.stop()

if df is None or df.empty:
    st.error("No chart data available.")
    st.stop()

ticker, ticker_err = cached_ticker(ccxt_symbol)
if ticker_err:
    if not is_rate_limit_message(ticker_err):
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

still_forming = "yes" if not bool(last_row.get("is_closed", True)) else "no"
updated = datetime.now(PAKISTAN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
st.caption(
    f"Data: Binance USDT-M Futures • Last updated: {updated} • "
    f"Last candle still forming: {still_forming}"
)