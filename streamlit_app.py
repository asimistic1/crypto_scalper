"""
Crypto Scalper — Phase 2: live chart + setup engine.
Run: streamlit run streamlit_app.py  (inside venv)
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import streamlit as st
from dotenv import load_dotenv

from core.auth_gate import require_auth
from core.data import TOP_SYMBOLS_FALLBACK
from core.rate_limit import BinanceCooldownActive, banner_message, is_in_cooldown
from core.symbol_ranking import display_to_rest
from core.weight_budget import weight_used_this_minute
from ui.setup_card import render_setup_card

ANALYZE_DEBOUNCE_SECONDS = 3

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Crypto Scalper", layout="wide", initial_sidebar_state="expanded")

if not require_auth():
    st.stop()

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; }
    @media (max-width: 900px) {
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_session() -> None:
    defaults = {
        "display_symbol": "BTC/USDT",
        "timeframe": "15m",
        "quote_volumes": {},
        "analysis_setup": None,
        "analysis_overlays": {},
        "analysis_diag": None,
        "last_analyzed_close_ms": 0,
        "last_analyze_ts": 0.0,
        "last_event_nonce": "",
        "last_chart_status": None,
        "analysis_context_key": "",
        "analyze_requested": False,
        "chart_latency_ms": None,
    }
    for key, val in defaults.items():
        st.session_state.setdefault(key, val)


@st.cache_data(ttl=300, show_spinner=False)
def cached_top_symbols_and_volumes() -> tuple[tuple[str, ...], dict[str, float]]:
    from core.symbol_ranking import fetch_top_symbols_by_volume

    try:
        return fetch_top_symbols_by_volume(30)
    except (BinanceCooldownActive, Exception):
        vols = {display_to_rest(s): 0.0 for s in TOP_SYMBOLS_FALLBACK}
        return tuple(TOP_SYMBOLS_FALLBACK), vols


@st.cache_resource(show_spinner=False)
def _storage_ready() -> bool:
    from core.storage import init_db

    init_db()
    return True


def _debounce_ok() -> bool:
    elapsed = time.time() - float(st.session_state.get("last_analyze_ts", 0.0))
    return elapsed >= ANALYZE_DEBOUNCE_SECONDS


def _record_analyze() -> None:
    st.session_state["last_analyze_ts"] = time.time()


def _run_analysis(toggles: dict[str, bool]) -> None:
    from core.analysis_service import run_analysis

    display = st.session_state["display_symbol"]
    tf = st.session_state["timeframe"]
    rest = display_to_rest(display)
    qv = float(st.session_state["quote_volumes"].get(rest, 0.0))
    try:
        result = run_analysis(display, tf, qv, toggles=toggles)
    except BinanceCooldownActive:
        st.warning(banner_message())
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Analysis failed: {exc}")
        return

    st.session_state["analysis_setup"] = result.setup
    st.session_state["analysis_overlays"] = result.overlays
    st.session_state["analysis_diag"] = result.diagnostics
    st.session_state["last_analyzed_close_ms"] = result.last_close_ms
    st.session_state["analysis_context_key"] = f"{rest}|{tf}"


def _handle_chart_event(event: dict | None) -> str | None:
    if not event or not isinstance(event, dict):
        return None
    nonce = str(event.get("nonce", ""))
    if nonce and nonce == st.session_state.get("last_event_nonce"):
        return None
    rest = display_to_rest(st.session_state["display_symbol"])
    if event.get("symbol") != rest or event.get("timeframe") != st.session_state["timeframe"]:
        return None
    st.session_state["last_event_nonce"] = nonce
    kind = event.get("event")
    if kind == "status_changed":
        setup_id = event.get("setup_id")
        status = event.get("status")
        if setup_id and status:
            from core.storage import update_signal_status

            update_signal_status(setup_id, str(status))
            st.session_state["last_chart_status"] = str(status)
        return None
    if kind == "candle_closed":
        return "candle_closed"
    return None


def _maybe_analyze(toggles: dict[str, bool], trigger: str | None) -> None:
    rest = display_to_rest(st.session_state["display_symbol"])
    ctx = f"{rest}|{st.session_state['timeframe']}"
    if ctx != st.session_state.get("analysis_context_key"):
        _run_analysis(toggles)
        _record_analyze()
        return
    if trigger == "candle_closed":
        _run_analysis(toggles)
        _record_analyze()
        return
    if st.session_state.get("analyze_requested"):
        if _debounce_ok():
            _run_analysis(toggles)
            _record_analyze()
            st.session_state["analyze_requested"] = False
        else:
            st.toast(f"Analyze cooldown — wait {ANALYZE_DEBOUNCE_SECONDS}s", icon="⏳")


_init_session()
_storage_ready()

st.title("Crypto Scalper")
st.caption("Binance USDT-M Perpetual · live WebSocket chart + setup engine")

if is_in_cooldown():
    st.warning(f"⏳ REST cooldown: {banner_message()}")

with st.sidebar:
    st.header("Settings")

    symbols, volumes = cached_top_symbols_and_volumes()
    st.session_state["quote_volumes"] = volumes

    if not symbols:
        symbols = tuple(TOP_SYMBOLS_FALLBACK)

    default_idx = symbols.index("BTC/USDT") if "BTC/USDT" in symbols else 0
    display_symbol = st.selectbox("Coin", symbols, index=default_idx)
    st.session_state["display_symbol"] = display_symbol

    timeframe = st.radio("Timeframe", ["5m", "15m", "1h"], index=1, horizontal=True)
    st.session_state["timeframe"] = timeframe

    history_limit = st.slider("History candles", 100, 1000, 500, 50)
    live_stream = st.toggle("Live stream", value=True)
    st.markdown("**Chart layers**")
    chart_toggles = {
        "zones": st.checkbox("Support / resistance zones", True),
        "swings": st.checkbox("Swing markers", True),
        "emas": st.checkbox("EMAs", True),
        "vwap": st.checkbox("VWAP", False),
        "setup_lines": st.checkbox("Setup lines", True),
    }

    if st.button("Analyze", use_container_width=True, type="primary"):
        if _debounce_ok():
            st.session_state["analyze_requested"] = True
        else:
            st.warning(f"Please wait {ANALYZE_DEBOUNCE_SECONDS}s between analyses.")

    st.caption(f"API weight this minute: **{weight_used_this_minute()}**")


@st.fragment
def chart_and_setup_panel() -> None:
    try:
        _chart_and_setup_panel_body()
    except Exception:
        logger.exception("chart_and_setup_panel failed")
        st.error("Something went wrong updating the chart. Try Refresh or Analyze again.")


def _chart_and_setup_panel_body() -> None:
    from core.candle_store import get_closed_candles
    from core.exchange_info import price_precision, tick_size
    from core.live_chart import render_live_chart

    toggles = chart_toggles
    rest = display_to_rest(st.session_state["display_symbol"])
    tf = st.session_state["timeframe"]

    chart_event = None
    chart_col, setup_col = st.columns([72, 28])

    fb_df = None
    if not is_in_cooldown():
        try:
            fb_df = get_closed_candles(rest, tf, full=True).df.tail(history_limit)
        except Exception:
            fb_df = None

    with chart_col:
        chart_event = render_live_chart(
            display_symbol,
            tf,
            overlays=st.session_state.get("analysis_overlays") or {},
            height=720,
            fallback_candles=fb_df,
            history_limit=history_limit,
            streaming_enabled=live_stream,
            tick_size=float(tick_size(rest)),
            toggles=toggles,
        )
        if isinstance(chart_event, dict):
            st.session_state["last_chart_event"] = chart_event

    trigger = _handle_chart_event(chart_event if isinstance(chart_event, dict) else None)
    _maybe_analyze(toggles, trigger)
    setup = st.session_state.get("analysis_setup")

    with setup_col:
        st.subheader("Setup Card")
        if setup:
            render_setup_card(
                setup,
                display_symbol,
                price_precision=price_precision(rest),
                live_status=st.session_state.get("last_chart_status"),
            )
        else:
            st.info("Analyzing…")

    with st.expander("Diagnostics", expanded=False):
        diag = st.session_state.get("analysis_diag")
        if diag:
            st.write(
                {
                    "fetch_ms": round(diag.fetch_ms, 1),
                    "indicators_ms": round(diag.indicators_ms, 1),
                    "levels_ms": round(diag.levels_ms, 1),
                    "setup_ms": round(diag.setup_ms, 1),
                    "cache_hits": diag.cache_hits,
                    "cache_misses": diag.cache_misses,
                }
            )
        st.caption(f"API weight this minute: **{weight_used_this_minute()}**")
        ev = st.session_state.get("last_chart_event")
        if ev:
            st.json(ev)


@st.fragment(run_every=timedelta(seconds=30))
def missed_candle_guard() -> None:
    """Lightweight tail fetch (~1 weight) if the browser missed a candle_closed event."""
    try:
        _missed_candle_guard_body()
    except Exception:
        logger.exception("missed_candle_guard failed")


def _missed_candle_guard_body() -> None:
    if is_in_cooldown():
        return
    from core.candle_store import get_closed_candles

    rest = display_to_rest(st.session_state.get("display_symbol", "BTC/USDT"))
    tf = st.session_state.get("timeframe", "15m")
    try:
        res = get_closed_candles(rest, tf)
        if res.df.empty:
            return
        last_ms = int(res.df["close_time"].iloc[-1])
        prev = int(st.session_state.get("last_analyzed_close_ms", 0))
        if last_ms > prev:
            toggles = {
                "zones": True,
                "swings": True,
                "emas": True,
                "vwap": False,
                "setup_lines": True,
            }
            _run_analysis(toggles)
            _record_analyze()
    except (BinanceCooldownActive, Exception):
        return


chart_and_setup_panel()
missed_candle_guard()

st.caption(
    "Live prices stream in the browser (Binance /market WebSocket). "
    "Analysis uses closed candles only — no look-ahead."
)