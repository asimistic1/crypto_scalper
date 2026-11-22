"""Test my idea — custom rule backtest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from core.auth_gate import require_auth
from core.idea_tester import RuleSpec, run_idea_test

RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "idea_rules.json"

st.set_page_config(page_title="Test idea", layout="wide")
if not require_auth():
    st.stop()

st.title("Test my idea")
st.caption("Reuses Phase 3 simulator and costs — results are research, not live signals.")

tested = 0
if RULES_PATH.exists():
    tested = len(json.loads(RULES_PATH.read_text(encoding="utf-8")))
st.info(f"Ideas tested so far: **{tested}**" + (" — multiple-testing caution after 10." if tested >= 10 else ""))

symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
tf = st.selectbox("Timeframe", ["5m", "15m", "1h"])
direction = st.selectbox("Direction", ["LONG", "SHORT", "both"])
conds = []
for i in range(4):
    c1, c2, c3 = st.columns(3)
    with c1:
        left = st.selectbox(f"Feature {i+1}", ["rsi_14", "close", "ema_200", "ema_50"], key=f"l{i}")
    with c2:
        op = st.selectbox("Op", ["<", ">", "<=", ">="], key=f"o{i}")
    with c3:
        right = st.text_input("Value / column", value="30" if i == 0 else "", key=f"r{i}")
    if right:
        conds.append({"left": left, "op": op, "right": right})

sl_atr = st.number_input("SL (ATR mult)", value=1.5, min_value=0.3)
tp_r = st.number_input("TP (R)", value=1.0, min_value=0.5)
hold = st.number_input("Max hold bars", value=32, min_value=1)
low_fee = st.checkbox("MEXC low-fee scenario", value=True)

spec = RuleSpec(symbol, tf, direction, conds, sl_atr, tp_r, hold, low_fee)
locked = st.session_state.get("idea_locked", False)

if st.button("Run in-sample", type="primary"):
    with st.spinner("Running…"):
        res = run_idea_test(spec)
    st.session_state["idea_result"] = res
    st.session_state["idea_locked"] = False

res = st.session_state.get("idea_result")
if res:
    st.json({k: res[k] for k in res if k != "trades"})
    if locked:
        st.subheader("OOS (locked rule)")
        st.write(res.get("OOS"))
        st.success(res.get("verdict"))
    else:
        st.warning("OOS hidden until you lock the rule.")
        if st.button("Lock rule and show out-of-sample"):
            RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
            rules = json.loads(RULES_PATH.read_text(encoding="utf-8")) if RULES_PATH.exists() else []
            rules.append(
                {"spec": spec.__dict__, "locked_at": datetime.now(UTC).isoformat(), "result": res}
            )
            RULES_PATH.write_text(json.dumps(rules, indent=2), encoding="utf-8")
            st.session_state["idea_locked"] = True
            st.rerun()