"""
Crypto Scalper — Phase 1: live WebSocket chart (browser ↔ Binance).
Run: streamlit run streamlit_app.py  (inside venv)
"""

from __future__ import annotations

import streamlit as st

from core.rate_limit import BinanceCooldownActive, banner_message, is_in_cooldown

from core.data import (
    TOP_SYMBOLS_FALLBACK,
    DataFetchError,
    bind_exchange,
    configure_network,
    create_binance_exchange,
    display_to_ccxt_symbol,
    fetch_ohlcv_dataframe,
    fetch_top_symbols_list,
    load_proxy_from_env,
    region_block_help_markdown,
    region_block_user_message,
    use_lightweight_binance,
)
from core.live_chart import render_live_chart
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

if not use_lightweight_binance():

    @st.cache_resource(show_spinner=False)
    def cached_binance_exchange(proxy_key: str):
        return create_binance_exchange(proxy_key or None)

    bind_exchange(cached_binance_exchange(_PROXY_KEY))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_top_symbols(n: int, fetch_volume_ranking: bool) -> tuple[str, ...]:
    return tuple(fetch_top_symbols_list(n, fetch_volume_ranking=fetch_volume_ranking))


@st.cache_data(ttl=600, show_spinner=False)
def bootstrap_candles(ccxt_symbol: str, timeframe: str, limit: int):
    """One-time Python fallback history for the iframe if browser CORS fails."""
    return fetch_ohlcv_dataframe(ccxt_symbol, timeframe, limit)


st.title("Crypto Scalper")
st.caption("Binance USDT-M Perpetual — live WebSocket chart (Last Price)")

if is_in_cooldown():
    st.warning(f"⏳ Python REST cooldown active (analysis only): {banner_message()}")

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

    if sym_err and sym_err not in (banner_message(), region_block_user_message()):
        st.warning(sym_err)
    if sym_err == region_block_user_message():
        st.warning(sym_err)
        with st.expander("Why is Binance blocked?"):
            st.markdown(region_block_help_markdown())

    if not symbols:
        symbols = list(TOP_SYMBOLS_FALLBACK)

    default_idx = symbols.index("BTC/USDT") if "BTC/USDT" in symbols else 0
    display_symbol = st.selectbox("Coin", symbols, index=default_idx)
    ccxt_symbol = display_to_ccxt_symbol(display_symbol)

    timeframe = st.radio("Timeframe", ["5m", "15m", "1h"], index=1, horizontal=True)
    history_limit = st.slider("History candles", min_value=100, max_value=1000, value=500, step=50)
    live_stream = st.toggle(
        "Live stream",
        value=True,
        help="When off, the chart pauses WebSocket updates until you turn it back on.",
    )
    show_demo_overlays = st.toggle(
        "Show demo overlays",
        value=False,
        help="Phase 2 placeholder lines/zones — off by default.",
    )
    st.markdown("**Chart layers**")
    toggle_zones = st.checkbox("Support / resistance zones", value=True)
    toggle_swings = st.checkbox("Swing markers", value=True)
    toggle_emas = st.checkbox("EMAs", value=True)
    toggle_vwap = st.checkbox("VWAP", value=False)
    toggle_setup = st.checkbox("Setup lines", value=True)

chart_col, setup_col = st.columns([4, 1])

fb_df = None
if not is_in_cooldown():
    try:
        fb_df = bootstrap_candles(ccxt_symbol, timeframe, history_limit)
    except Exception:
        fb_df = None

overlays = None
if show_demo_overlays and fb_df is not None and not fb_df.empty:
    close = float(fb_df.iloc[-1]["close"])
    overlays = {
        "lines": [{"price": close, "color": "#2962FF", "title": "Entry (demo)", "style": "solid"}],
        "zones": [
            {
                "from": close * 0.998,
                "to": close * 1.002,
                "color": "rgba(14,203,129,0.35)",
                "label": "Support (demo)",
            }
        ],
    }

chart_toggles = {
    "zones": toggle_zones,
    "swings": toggle_swings,
    "emas": toggle_emas,
    "vwap": toggle_vwap,
    "setup_lines": toggle_setup,
}

with chart_col:
    chart_event = render_live_chart(
        ccxt_symbol,
        timeframe,
        overlays=overlays,
        height=750,
        fallback_candles=fb_df,
        history_limit=history_limit,
        streaming_enabled=live_stream,
        toggles=chart_toggles,
    )
    if chart_event:
        st.session_state["last_chart_event"] = chart_event

with setup_col:
    st.subheader("Trade Setup")
    st.info("Setup analysis coming in Phase 2. Overlays will be drawn on the live chart.")

st.caption(
    "Live data streams from your browser to Binance Futures (/market WebSocket). "
    "Streamlit does not poll prices — match against Binance app → BTCUSDT Perpetual → Last Price."
)