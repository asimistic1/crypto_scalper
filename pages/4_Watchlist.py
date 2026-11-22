"""Watchlist — information only."""

from __future__ import annotations

import streamlit as st

from core.auth_gate import require_auth
from core.mini_ticker import render_mini_ticker
from core.settings_store import load_settings
from core.symbol_ranking import fetch_top_symbols_by_volume
from core.watchlist_service import build_watch_row

st.set_page_config(page_title="Watchlist", layout="wide")
if not require_auth():
    st.stop()

st.title("Watchlist")
st.caption("Information only — not trade signals.")

settings = load_settings()
coins = [str(s).upper() for s in (settings.get("watchlist") or [])]
if not coins:
    try:
        syms, _ = fetch_top_symbols_by_volume(15)
        coins = [s.replace("/", "").upper() if s.endswith("USDT") else s.replace("/", "") + "USDT" for s in syms]
    except Exception:
        coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

filter_mode = st.selectbox("Filter", ["All", "Near zone (<0.5 ATR)", "All TF aligned", "High vol (ATR%)"])

live_event = render_mini_ticker(coins)
live_prices: dict = {}
if isinstance(live_event, dict) and live_event.get("event") == "watch_prices":
    live_prices = live_event.get("prices") or {}

rows = []
for sym in coins[:30]:
    wr = build_watch_row(sym)
    if wr:
        live = live_prices.get(sym)
        if live:
            wr.price = float(live.get("c", wr.price))
            wr.change_24h_pct = float(live.get("P", wr.change_24h_pct))
        rows.append(wr)

if filter_mode == "Near zone (<0.5 ATR)":
    rows = [r for r in rows if r.near_zone]
elif filter_mode == "All TF aligned":
    rows = [r for r in rows if r.aligned]
elif filter_mode == "High vol (ATR%)":
    rows = sorted(rows, key=lambda r: r.atr_pct, reverse=True)

table = [
    {
        "Coin": r.display,
        "Live price": r.price,
        "24h %": round(r.change_24h_pct, 2),
        "15m": r.trend_15m,
        "1h": r.trend_1h,
        "4h": r.trend_4h,
        "Dist S %": round(r.dist_support_pct or 0, 2),
        "ATR%": round(r.atr_pct, 2),
        "RSI": round(r.rsi or 0, 1),
        "Funding": r.funding,
    }
    for r in rows
]
st.dataframe(table, use_container_width=True)
if live_prices:
    st.caption(f"Live prices: **{len(live_prices)}** symbols via Binance `!miniTicker@arr` (browser WebSocket).")

if st.button("Open Live chart"):
    st.switch_page("streamlit_app.py")