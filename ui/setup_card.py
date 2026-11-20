"""
Setup Card UI — Phase 2 trade setup panel.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import streamlit as st

from core.models import Direction, EntryType, Setup, TrendBias

PK = ZoneInfo("Asia/Karachi")


def _fmt_pk(dt) -> str:
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PK).strftime("%d %b %Y, %H:%M") + " PKT"


def _direction_badge(setup: Setup) -> str:
    if setup.direction == Direction.LONG:
        return "🟢 LONG"
    if setup.direction == Direction.SHORT:
        return "🔴 SHORT"
    return "⚪ NO TRADE"


def _htf_line(setup: Setup) -> str:
    parts: list[str] = []
    for tf, tr in sorted(setup.htf_trends.items()):
        label = tr.bias.value.capitalize()
        parts.append(f"{tf} {label}")
    return " · ".join(parts) if parts else "—"


def _copy_line(setup: Setup, display_symbol: str) -> str:
    if setup.direction == Direction.NO_TRADE:
        return f"{display_symbol} {setup.timeframe} NO TRADE"
    et = setup.entry_type.value
    return (
        f"{display_symbol} {setup.timeframe} {setup.direction.value} | "
        f"Entry {setup.entry:.4f} ({et}) | "
        f"SL {setup.stop_loss:.4f} ({setup.sl_pct:+.2f}%) | "
        f"TP1 {setup.tp1:.4f} | TP2 {setup.tp2:.4f} | TP3 {setup.tp3:.4f} | "
        f"Net R:R TP1 {setup.net_rr[0]:.2f} | Score {setup.score:.0f}/100"
    )


def render_setup_card(
    setup: Setup,
    display_symbol: str,
    *,
    live_status: str | None = None,
) -> None:
    """Right-hand setup panel."""
    st.markdown(f"### {_direction_badge(setup)}")
    st.caption(f"{setup.strategy} · {setup.timeframe} · {_fmt_pk(setup.as_of)}")

    if live_status:
        st.info(f"Live chart status: **{live_status}**")

    if setup.direction == Direction.NO_TRADE:
        for r in setup.reasons:
            if r.startswith("✖"):
                st.error(r)
            elif r.startswith("⚠"):
                st.warning(r)
            else:
                st.write(r)
        if setup.rejected_candidate:
            st.markdown("---")
            st.caption("Rejected candidate (below min setup score)")
            rc = setup.rejected_candidate
            st.markdown(
                f'<p style="opacity:0.6">{rc.direction.value} {rc.strategy} — '
                f"score {rc.score:.0f}/100</p>",
                unsafe_allow_html=True,
            )
            for r in rc.reasons[:8]:
                st.caption(r)
        return

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Entry", f"{setup.entry:.4f}", f"{setup.entry_type.value}")
    with c2:
        st.metric("Stop", f"{setup.stop_loss:.4f}", f"{setup.sl_pct:.2f}%")

    tp_cols = st.columns(3)
    for col, label, tp, pct, rr in zip(
        tp_cols,
        ("TP1", "TP2", "TP3"),
        (setup.tp1, setup.tp2, setup.tp3),
        setup.tp_pcts,
        setup.net_rr,
    ):
        with col:
            st.metric(label, f"{tp:.4f}", f"{pct:.2f}% · net R {rr:.2f}")

    st.progress(min(1.0, setup.score / 100.0), text=f"Setup Score {setup.score:.0f}/100")
    st.caption("Win confidence: available after Phase 4 (calibrated on historical results)")

    htf = _htf_line(setup)
    if htf != "—":
        badges = []
        for tf, tr in sorted(setup.htf_trends.items()):
            icon = "🟢" if tr.bias == TrendBias.BULLISH else "🔴" if tr.bias == TrendBias.BEARISH else "⚪"
            badges.append(f"{icon} {tf}")
        st.write("HTF: " + " · ".join(badges))
        st.caption(htf)

    with st.expander("Reasons", expanded=True):
        for r in setup.reasons:
            if r.startswith("✖"):
                st.error(r)
            elif r.startswith("⚠"):
                st.warning(r)
            else:
                st.success(r)

    with st.expander("Score breakdown"):
        b = setup.breakdown
        st.write(
            {
                "HTF": b.htf,
                "Levels": b.level_quality,
                "Momentum": b.momentum,
                "Volume": b.volume,
                "Candle": b.candle_confirmation,
                "Net R:R": b.net_rr,
                "Volatility": b.volatility,
                "Penalties": b.penalties,
                "Total": b.total,
            }
        )

    st.text_area("Copy summary", value=_copy_line(setup, display_symbol), height=68)