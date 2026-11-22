"""Test my idea — custom rule backtest with strict IS/OOS lock."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from core.auth_gate import require_auth
from core.idea_tester import (
    RuleSpec,
    feature_options,
    load_cached,
    locked_rules_count,
    rule_hash,
    run_idea_test,
)

RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "idea_rules.json"

st.set_page_config(page_title="Test idea", layout="wide")
if not require_auth():
    st.stop()

st.title("Test my idea")
st.caption("Research only — OOS is hidden until you lock the rule.")

locked_n = locked_rules_count()
st.info(
    f"You have locked **{locked_n}** idea(s)."
    + (" Multiple-testing caution at ≥10." if locked_n >= 10 else "")
)

opts = list(feature_options())

symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], key="idea_sym")
tf = st.selectbox("Timeframe", ["5m", "15m", "1h"], key="idea_tf")

st.markdown("**Long entry conditions** (AND, up to 4)")
long_conds = []
for i in range(4):
    c1, c2, c3 = st.columns(3)
    with c1:
        left = st.selectbox(f"L feat {i+1}", opts, key=f"ll{i}")
    with c2:
        op = st.selectbox("Op", ["<", ">", "<=", ">="], key=f"lo{i}")
    with c3:
        right = st.text_input("Value", value="30" if i == 0 else "", key=f"lr{i}")
    if right:
        long_conds.append({"left": left, "op": op, "right": right})

st.markdown("**Short entry conditions** (AND, up to 4)")
short_conds = []
for i in range(4):
    c1, c2, c3 = st.columns(3)
    with c1:
        left = st.selectbox(f"S feat {i+1}", opts, key=f"sl{i}")
    with c2:
        op = st.selectbox("Op", ["<", ">", "<=", ">="], key=f"so{i}")
    with c3:
        right = st.text_input("Value", value="70" if i == 0 else "", key=f"sr{i}")
    if right:
        short_conds.append({"left": left, "op": op, "right": right})

sl_atr = st.number_input("SL (ATR mult)", value=1.5, min_value=0.3, key="idea_sl")
tp_r = st.number_input("TP (R)", value=1.0, min_value=0.5, key="idea_tp")
hold = st.number_input("Max hold bars", value=32, min_value=1, key="idea_hold")
low_fee = st.checkbox("MEXC low-fee scenario", value=True, key="idea_fee")

spec = RuleSpec(symbol, tf, long_conds, short_conds, sl_atr, tp_r, hold, low_fee)
fp = rule_hash(spec)

if st.session_state.get("idea_spec_hash") and st.session_state.get("idea_spec_hash") != fp:
    st.session_state.pop("idea_is_result", None)
    st.session_state.pop("idea_oos_result", None)
    st.session_state.pop("idea_locked_spec", None)
st.session_state["idea_spec_hash"] = fp

running = st.session_state.get("idea_job_running") and st.session_state.get("idea_job_hash") == fp

if st.button("Run in-sample", type="primary", disabled=running):
    st.session_state["idea_job_running"] = True
    st.session_state["idea_job_hash"] = fp
    st.session_state.pop("idea_locked_spec", None)
    st.session_state.pop("idea_oos_result", None)
    st.session_state.pop("idea_is_result", None)

    def _work(s: RuleSpec) -> None:
        run_idea_test(s, phase="IS", use_cache=True)

    threading.Thread(target=_work, args=(spec,), daemon=True).start()
    st.rerun()

if running:
    hit = load_cached(spec, "IS")
    if hit is not None:
        st.session_state["idea_is_result"] = hit
        st.session_state["idea_job_running"] = False
        st.rerun()
    st.info("Running in-sample… (background)")

is_res = st.session_state.get("idea_is_result")
if is_res and is_res.get("hash") == fp:
    st.subheader("In-sample results")
    st.json({k: v for k, v in is_res.items() if k not in ("trades",)})

    if st.button("Lock rule and show out-of-sample"):
        RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8")) if RULES_PATH.exists() else []
        record = {
            "spec": asdict(spec),
            "hash": rule_hash(spec),
            "locked_at": datetime.now(UTC).isoformat(),
            "is_snapshot": is_res.get("IS"),
        }
        rules.append(record)
        RULES_PATH.write_text(json.dumps(rules, indent=2), encoding="utf-8")
        st.session_state["idea_locked_spec"] = record
        locked = RuleSpec.from_dict(record["spec"])
        oos = run_idea_test(locked, phase="OOS", use_cache=True)
        st.session_state["idea_oos_result"] = oos
        st.rerun()

oos_res = st.session_state.get("idea_oos_result")
locked_spec = st.session_state.get("idea_locked_spec")
if oos_res and locked_spec and locked_spec.get("hash") == fp:
    st.subheader("Out-of-sample (locked rule)")
    st.json({k: v for k, v in oos_res.items() if k != "trades"})
    st.write(f"**Verdict:** {oos_res.get('verdict', '—')}")