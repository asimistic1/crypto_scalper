"""Trade journal and stats."""

from __future__ import annotations

import streamlit as st

from core.auth_gate import require_auth
from core.journal import export_csv, import_csv, init_journal_db, list_trades, stats_summary, update_trade

st.set_page_config(page_title="Journal", layout="wide")
if not require_auth():
    st.stop()

init_journal_db()
st.title("Trade journal")

summary = stats_summary()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Trades (closed)", int(summary.get("count", 0)))
c2.metric("Win rate", f"{summary.get('win_rate', 0):.1%}" if summary.get("count") else "—")
c3.metric("Avg R", f"{summary.get('avg_r', 0):.3f}" if summary.get("count") else "—")
c4.metric("Max DD (R)", f"{summary.get('max_dd_r', 0):.2f}" if summary.get("count") else "—")

trades = list_trades()
if trades:
    st.dataframe(trades, use_container_width=True)
    pick = st.selectbox("Update trade", [t["id"] for t in trades])
    row = next(t for t in trades if t["id"] == pick)
    with st.form("update"):
        actual = st.number_input("Actual entry", value=float(row.get("actual_entry") or 0.0))
        exit_p = st.number_input("Exit price", value=float(row.get("exit_price") or 0.0))
        outcome = st.number_input("Outcome R", value=float(row.get("outcome_r") or 0.0))
        emotion = st.selectbox("Emotion", ["", "calm", "FOMO", "revenge", "bored"])
        followed = st.checkbox("Followed plan", value=bool(row.get("followed_plan")))
        notes = st.text_area("Notes", value=row.get("notes") or "", max_chars=1000)
        if st.form_submit_button("Save"):
            update_trade(
                int(pick),
                actual_entry=actual or None,
                exit_price=exit_p or None,
                outcome_r=outcome,
                emotion=emotion,
                notes=notes,
                followed_plan=1 if followed else 0,
            )
            st.rerun()

st.download_button("Export CSV", export_csv(), file_name="journal.csv", mime="text/csv")
uploaded = st.file_uploader("Import CSV (validated)")
if uploaded:
    n = import_csv(uploaded.getvalue().decode("utf-8", errors="replace"))
    st.info(f"Imported {n} rows.")