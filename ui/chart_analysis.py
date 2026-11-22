"""Chart Analysis panel — information only, not recommendations."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import streamlit as st

from core.market_analysis import ChartAnalysis
from core.models import TrendBias

PK = ZoneInfo("Asia/Karachi")


def _fmt_pk(dt) -> str:
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PK).strftime("%d %b %Y, %H:%M") + " PKT"


def _trend_icon(bias: TrendBias) -> str:
    if bias == TrendBias.BULLISH:
        return "🟢"
    if bias == TrendBias.BEARISH:
        return "🔴"
    return "⚪"


def render_chart_analysis(analysis: ChartAnalysis, *, price_precision: int = 4) -> None:
    st.caption(f"{analysis.timeframe} · {_fmt_pk(analysis.as_of)} · analysis only (not a signal)")
    st.markdown("**HTF trend**")
    if analysis.htf_trends:
        lines = []
        for tf, tr in sorted(analysis.htf_trends.items()):
            lines.append(f"{_trend_icon(tr.bias)} **{tf}** — {tr.bias.value.capitalize()}")
        st.markdown(" · ".join(lines))
    else:
        st.write("—")

    st.markdown("**Support / resistance (nearest)**")
    for z in analysis.nearest_support:
        st.write(
            f"S {z.near_edge:,.{price_precision}f} — {z.distance_pct:.2f}% away · "
            f"×{z.touches} touches · strength {z.strength:.1f}"
        )
    for z in analysis.nearest_resistance:
        st.write(
            f"R {z.near_edge:,.{price_precision}f} — {z.distance_pct:.2f}% away · "
            f"×{z.touches} touches · strength {z.strength:.1f}"
        )
    if not analysis.nearest_support and not analysis.nearest_resistance:
        st.caption("No zones within search radius.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("ATR%", f"{analysis.atr_pct:.2f}%", analysis.volatility_state)
    with c2:
        rsi = analysis.rsi_14
        st.metric("RSI(14)", f"{rsi:.1f}" if rsi is not None else "—")
    with c3:
        st.metric("VWAP", analysis.vwap_position)

    st.caption(f"MACD: {analysis.macd_state}")

    if analysis.patterns:
        st.markdown("**Patterns detected**")
        for p in analysis.patterns:
            st.warning(f"{p.label} ({p.direction}) — {p.warning}")
    else:
        st.caption("_Patterns hidden — enable “Show detected patterns” in the sidebar._")

    if analysis.context_notes:
        with st.expander("Context notes", expanded=False):
            for n in analysis.context_notes:
                st.write(n)