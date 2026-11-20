"""
Backtest dashboard (read-only Parquet from data/backtest/runs).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from core.auth_gate import require_auth

st.set_page_config(page_title="Backtest", layout="wide")
if not require_auth():
    st.stop()

RUNS = Path("data/backtest/runs")


@st.cache_data(show_spinner=False)
def load_run(run_id: str) -> tuple[pd.DataFrame, dict]:
    run_dir = RUNS / run_id
    trades = pd.read_parquet(run_dir / "trades.parquet")
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return trades, summary


def main() -> None:
    st.title("Backtest results")
    if not RUNS.exists():
        st.info("No runs yet. Execute: python -m backtest.run …")
        return
    runs = sorted([p.name for p in RUNS.iterdir() if p.is_dir()], reverse=True)
    if not runs:
        st.info("No runs yet.")
        return
    run_id = st.selectbox("Run", runs)
    trades, summary = load_run(run_id)

    exit_model = st.selectbox("Exit model", sorted(trades["exit_model"].unique()))
    symbol = st.multiselect("Symbol", sorted(trades["symbol"].unique()), default=sorted(trades["symbol"].unique()))
    tf = st.multiselect("Timeframe", sorted(trades["timeframe"].unique()), default=sorted(trades["timeframe"].unique()))

    filt = trades[
        (trades["exit_model"] == exit_model)
        & (trades["symbol"].isin(symbol))
        & (trades["timeframe"].isin(tf))
        & (trades["filled"])
    ]
    if filt.empty:
        st.warning("No filled trades for filters.")
        return

    col1, col2, col3, col4 = st.columns(4)
    wins = filt[filt["outcome"].isin(("TP1", "TP2", "TP3", "BE"))]
    col1.metric("Trades", len(filt))
    col2.metric("Win rate", f"{100 * len(wins) / len(filt):.1f}%")
    col3.metric("Expectancy (R)", f"{filt['r_net'].mean():.3f}")
    col4.metric("Total net R", f"{filt['r_net'].sum():.2f}")

    eq = filt.sort_values("signal_time")["r_net"].cumsum()
    st.subheader("Equity curve (R)")
    st.line_chart(eq.reset_index(drop=True))

    dd = eq - eq.cummax()
    st.subheader("Drawdown (R)")
    st.line_chart(dd.reset_index(drop=True))

    st.subheader("Trades")
    st.dataframe(filt.sort_values("signal_time"), use_container_width=True, height=320)

    st.subheader("Run summary (JSON)")
    st.json(summary.get("by_slice", {}))


main()