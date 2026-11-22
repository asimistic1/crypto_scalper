"""Console tables and summary artifacts for Phase 3.3+."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.metrics import too_good_alarm


def _fmt_ci(lo: float, hi: float) -> str:
    return f"[{lo:.1%}-{hi:.1%}]"


def _fmt_rb(rb: dict[str, Any]) -> str:
    return (
        f"{rb.get('percentile', 0):.0f}% "
        f"μ={rb.get('mean', 0):.3f} σ={rb.get('std', 0):.3f} "
        f"p5/50/95={rb.get('p5', 0):.3f}/{rb.get('p50', 0):.3f}/{rb.get('p95', 0):.3f}"
    )


def print_slice_table(summary: dict[str, Any], cal_oos_by_model: dict[str, pd.DataFrame]) -> str:
    lines: list[str] = []
    lines.append("\n=== Metrics by symbol / tf / exit model (IS | OOS) ===")
    header = (
        "slice | sample | signals | taken | fill% | WR(TP1<SL) | avgW | avgL | E[R] | PF | "
        "totR | maxDD | MC95DD | random baseline | rho | cost1.5E | cost2.0E"
    )
    lines.append(header)
    for key in sorted(summary.get("by_slice", {})):
        parts = summary["by_slice"][key]
        for sample in ("IS", "OOS"):
            m = parts.get(sample, {})
            if not m:
                continue
            wci = m.get("win_rate_ci", (0.0, 0.0))
            eci = m.get("expectancy_ci", (0.0, 0.0))
            rb = m.get("random_baseline", {})
            rb_txt = _fmt_rb(rb) if rb else f"{m.get('random_baseline_pct', 0):.0f}%"
            lines.append(
                f"{key} | {sample} | {m.get('signals', 0)} | {m.get('trades_taken', m.get('trades', 0))} | "
                f"{m.get('fill_rate', 0):.1%} | {m.get('win_rate', 0):.1%}{_fmt_ci(*wci)} | "
                f"{m.get('avg_win_r', 0):.2f} | {m.get('avg_loss_r', 0):.2f} | "
                f"{m.get('expectancy_r', 0):.3f}{_fmt_ci(*eci)} | {m.get('profit_factor', 0):.2f} | "
                f"{m.get('total_net_r', 0):.1f} | {m.get('max_dd_r', 0):.2f} | {m.get('mc_dd_95', 0):.2f} | "
                f"{rb_txt} | {m.get('spearman_score_r', '')} | "
                f"{m.get('cost_1_5_expectancy', 0):.3f} | {m.get('cost_2_0_expectancy', 0):.3f}"
            )
    for model_key in sorted(cal_oos_by_model):
        cal = cal_oos_by_model[model_key]
        lines.append(f"\n=== OOS score calibration — {model_key} ===")
        if cal is not None and not cal.empty:
            lines.append(cal.to_string(index=False))
        else:
            lines.append("(no OOS trades)")
    alarms = summary.get("alarms", [])
    if alarms:
        lines.append("\n=== Alarms ===")
        lines.extend(alarms)
    text = "\n".join(lines)
    print(text)
    return text


def write_summary(run_dir: Path, summary: dict[str, Any], text: str) -> None:
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (run_dir / "summary.txt").write_text(text, encoding="utf-8")


def collect_alarms(summary: dict[str, Any]) -> None:
    alarms: list[str] = []
    for key, parts in summary.get("by_slice", {}).items():
        m = parts.get("OOS", {})
        sym = key.split("|")[0]
        for line in too_good_alarm(m, f"OOS {sym}"):
            alarms.append(line)
    summary["alarms"] = alarms