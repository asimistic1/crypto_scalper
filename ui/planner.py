"""Plan a trade — Streamlit panel."""

from __future__ import annotations

import streamlit as st

from core.exchange_info import step_size, tick_size
from core.planner import FeeConfig, PlannerInput, build_plan, format_mexc_plan, snap_price
from core.symbol_ranking import display_to_rest


def _init_planner_state() -> None:
    defaults = {
        "plan_direction": "LONG",
        "plan_entry": 0.0,
        "plan_sl": 0.0,
        "plan_tp1": 0.0,
        "plan_tp2": 0.0,
        "plan_tp3": 0.0,
        "plan_balance": 1000.0,
        "plan_risk_pct": 0.5,
        "plan_leverage": 10,
        "plan_entry_type": "market",
        "click_pick_field": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def apply_price_pick(event: dict | None, symbol_display: str) -> None:
    if not event or event.get("event") != "price_pick":
        return
    if display_to_rest(symbol_display) != event.get("symbol"):
        return
    field = event.get("field")
    price = float(event.get("price") or 0)
    if not price:
        return
    rest = display_to_rest(symbol_display)
    tick = float(tick_size(rest))
    snapped = snap_price(price, tick)
    key_map = {
        "entry": "plan_entry",
        "sl": "plan_sl",
        "tp1": "plan_tp1",
        "tp2": "plan_tp2",
        "tp3": "plan_tp3",
    }
    if field in key_map:
        st.session_state[key_map[field]] = snapped


def render_trade_planner(symbol_display: str, *, atr: float | None, zone_prices: tuple[float, ...]) -> str | None:
    """Returns click_pick mode for chart component (or empty)."""
    _init_planner_state()
    rest = display_to_rest(symbol_display)
    st.markdown("**Plan a trade**")
    st.caption("Information only — nothing is sent to any exchange.")

    direction = st.radio("Direction", ["LONG", "SHORT"], horizontal=True, key="plan_direction_radio")
    st.session_state["plan_direction"] = direction
    entry_type = st.selectbox("Entry type", ["market", "limit"], key="plan_entry_type_sel")
    st.session_state["plan_entry_type"] = entry_type

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Set entry", use_container_width=True):
            st.session_state["click_pick_field"] = "entry"
    with c2:
        if st.button("Set SL", use_container_width=True):
            st.session_state["click_pick_field"] = "sl"
    with c3:
        if st.button("Clear pick", use_container_width=True):
            st.session_state["click_pick_field"] = ""

    tp_cols = st.columns(3)
    for col, fld, lbl in zip(tp_cols, ("tp1", "tp2", "tp3"), ("TP1", "TP2", "TP3"), strict=True):
        with col:
            if st.button(f"Set {lbl}", use_container_width=True):
                st.session_state["click_pick_field"] = fld

    tick = float(tick_size(rest))
    step = float(step_size(rest))

    entry = st.number_input("Entry", value=float(st.session_state.get("plan_entry") or 0.0), format="%.8f")
    sl = st.number_input("Stop loss", value=float(st.session_state.get("plan_sl") or 0.0), format="%.8f")
    tp1 = st.number_input("TP1", value=float(st.session_state.get("plan_tp1") or 0.0), format="%.8f")
    tp2 = st.number_input("TP2 (opt)", value=float(st.session_state.get("plan_tp2") or 0.0), format="%.8f")
    tp3 = st.number_input("TP3 (opt)", value=float(st.session_state.get("plan_tp3") or 0.0), format="%.8f")
    st.session_state.update({"plan_entry": entry, "plan_sl": sl, "plan_tp1": tp1, "plan_tp2": tp2, "plan_tp3": tp3})

    bal = st.number_input("Account balance (USDT)", min_value=0.0, value=float(st.session_state["plan_balance"]))
    risk = st.number_input("Risk %", min_value=0.01, max_value=10.0, value=float(st.session_state["plan_risk_pct"]))
    if risk > 1.0:
        st.warning("Risk above 1% — size carefully.")
    lev = st.number_input("Leverage", min_value=1, max_value=125, value=int(st.session_state["plan_leverage"]))

    maker = st.session_state.get("fee_maker", 0.0001)
    taker = st.session_state.get("fee_taker", 0.0004)
    mmr = st.session_state.get("maint_margin_rate", 0.004)

    inp = PlannerInput(
        direction=direction,  # type: ignore[arg-type]
        entry=snap_price(entry, tick),
        stop_loss=snap_price(sl, tick),
        balance_usdt=bal,
        risk_pct=risk,
        leverage=float(lev),
        entry_type=entry_type,  # type: ignore[arg-type]
        tp1=tp1 or None,
        tp2=tp2 or None,
        tp3=tp3 or None,
        tick_size=tick,
        step_size=step,
        maint_margin_rate=mmr,
        fees=FeeConfig(maker=maker, taker=taker),
        atr=atr,
        zone_prices=zone_prices,
    )
    plan = build_plan(inp)
    pos = plan["position"]
    st.metric("Position", f"{pos['coins']} coins", f"~{pos['notional_usdt']:.2f} USDT")
    if pos.get("below_min_notional"):
        st.error("Below min notional for this symbol.")
    st.write(f"Margin ~**{plan['margin_usdt']:.2f} USDT** · liq (approx) **{plan.get('liquidation_approx')}**")
    st.write(f"Fees ~{plan['fees']['round_trip_usdt']:.4f} USDT ({plan['fees']['round_trip_r']:.3f} R)")
    for w in plan["warnings"]:
        st.warning(w)
    for t in plan["targets"]:
        st.caption(f"{t['tp']}: gross {t['gross_r']:.2f}R · net {t['net_r']:.2f}R")
    if st.button("Copy plan", use_container_width=True):
        st.code(format_mexc_plan(symbol_display, inp, plan))
    reason = st.text_area("My reason", max_chars=1000, height=80)
    chk = st.multiselect(
        "Checklist",
        ["Trend aligned", "At a zone", "News risk checked"],
    )
    if st.button("Save to journal", use_container_width=True):
        from datetime import UTC, datetime

        from core.journal import JournalEntry, insert_trade

        tf = st.session_state.get("timeframe", "15m")
        insert_trade(
            JournalEntry(
                id=None,
                symbol=rest,
                timeframe=tf,
                direction=direction,
                planned_entry=inp.entry,
                planned_sl=inp.stop_loss,
                planned_tp1=inp.tp1,
                planned_tp2=inp.tp2,
                planned_tp3=inp.tp3,
                size_coins=float(pos.get("coins", 0)),
                risk_pct=risk,
                reason=reason,
                checklist=", ".join(chk),
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        st.success("Saved to journal.")
    st.session_state.update({"plan_balance": bal, "plan_risk_pct": risk, "plan_leverage": lev})
    return st.session_state.get("click_pick_field") or None