"""Watchlist — information only."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from core.auth_gate import require_auth
from core.settings_store import load_settings
from core.symbol_ranking import fetch_top_symbols_by_volume
from core.watchlist_service import build_watch_row

st.set_page_config(page_title="Watchlist", layout="wide")
if not require_auth():
    st.stop()

st.title("Watchlist")
st.caption("Information only — not trade signals.")

settings = load_settings()
coins = settings.get("watchlist") or []
if not coins:
    try:
        syms, _ = fetch_top_symbols_by_volume(15)
        coins = [s.replace("/", "") + ("" if "USDT" in s else "") for s in syms]
        coins = [c if c.endswith("USDT") else c + "USDT" for c in [s.replace("/", "") for s in syms]]
    except Exception:
        coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

filter_mode = st.selectbox("Filter", ["All", "Near zone (<0.5 ATR)", "All TF aligned", "High vol (ATR%)"])

components.html(
    """
<script>
(function(){
  if (window.__watchWs) return;
  const ws = new WebSocket('wss://fstream.binance.com/market/stream?streams=!miniTicker@arr');
  window.__watchWs = ws;
  const prices = {};
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      const arr = msg.data;
      if (!Array.isArray(arr)) return;
      arr.forEach((t) => {
        if (t.s && t.s.endsWith('USDT')) prices[t.s] = {c: +t.c, P: +t.P};
      });
      window.parent.postMessage({type: 'watch_prices', prices}, '*');
    } catch(e) {}
  };
})();
</script>
""",
    height=0,
)

rows = []
for sym in coins[:30]:
    wr = build_watch_row(sym)
    if wr:
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
        "Price": r.price,
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
if st.button("Open BTC on Live"):
    st.switch_page("streamlit_app.py")