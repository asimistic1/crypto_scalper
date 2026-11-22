"""App settings."""

from __future__ import annotations

import streamlit as st

from core.auth_gate import require_auth
from core.settings_store import DEFAULTS, load_settings, save_settings

st.set_page_config(page_title="Settings", layout="wide")
if not require_auth():
    st.stop()

st.title("Settings")
cur = load_settings()
with st.form("settings"):
    maker = st.number_input("Maker fee", value=float(cur["fee_maker"]), format="%.5f")
    taker = st.number_input("Taker fee", value=float(cur["fee_taker"]), format="%.5f")
    risk = st.number_input("Default risk %", value=float(cur["default_risk_pct"]))
    bal = st.number_input("Default balance USDT", value=float(cur["account_balance"]))
    mmr = st.number_input("Maintenance margin rate", value=float(cur["maint_margin_rate"]), format="%.4f")
    tz = st.text_input("Timezone", value=str(cur["timezone"]))
    wl = st.text_area("Watchlist (comma REST symbols)", value=",".join(cur["watchlist"]))
    if st.form_submit_button("Save"):
        save_settings(
            {
                "fee_maker": maker,
                "fee_taker": taker,
                "default_risk_pct": risk,
                "account_balance": bal,
                "maint_margin_rate": mmr,
                "timezone": tz,
                "watchlist": [s.strip().upper() for s in wl.split(",") if s.strip()],
            }
        )
        for k, v in (
            ("fee_maker", maker),
            ("fee_taker", taker),
            ("maint_margin_rate", mmr),
        ):
            st.session_state[k] = v
        st.success("Saved.")
st.caption(f"Defaults: {DEFAULTS}")