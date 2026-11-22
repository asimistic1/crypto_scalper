"""Copy run artifacts into tracked reports/ + what-if markdown."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from backtest.paths import REPO_ROOT

REPORTS_DIR = REPO_ROOT / "reports"


def _get(payload: dict[str, Any], tf: str, sample: str, key: str) -> Any:
    return payload.get(f"{tf}_{sample}_{key}")


def build_whatif_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 3.4 — BTCUSDT what-if & loss diagnostics",
        "",
        "IS = in-sample (exploration). **OOS = out-of-sample — do not tune on OOS.**",
        "",
    ]
    for tf in ("5m", "15m", "1h"):
        if not any(k.startswith(f"{tf}_") for k in payload):
            continue
        lines.append(f"## BTCUSDT {tf}")
        lines.append("")
        g_is = _get(payload, tf, "IS", "gross_vs_net") or {}
        g_oos = _get(payload, tf, "OOS", "gross_vs_net") or {}
        lines.append("### Gross vs net E[R]")
        lines.append("| metric | IS | OOS |")
        lines.append("| --- | ---: | ---: |")
        for k, label in (
            ("expectancy_gross_r", "Expectancy gross R"),
            ("expectancy_net_r", "Expectancy net R"),
            ("avg_cost_r_per_trade", "Avg cost (R/trade)"),
            ("median_cost_r", "Median cost R"),
        ):
            lines.append(
                f"| {label} | {g_is.get(k, '—'):.4f} | {g_oos.get(k, '—'):.4f} |"
                if isinstance(g_is.get(k), (int, float))
                else f"| {label} | — | — |"
            )
        lines.append("")

        sl_is = _get(payload, tf, "IS", "sl") or {}
        sl_oos = _get(payload, tf, "OOS", "sl") or {}
        b_is = sl_is.get("cost_as_pct_of_gross_r_buckets", {})
        b_oos = sl_oos.get("cost_as_pct_of_gross_r_buckets", {})
        lines.append("### Cost as % of gross R (trade count)")
        lines.append("| bucket | IS | OOS |")
        lines.append("| --- | ---: | ---: |")
        for b in ("<10%", "10-20%", "20-33%", ">33%"):
            lines.append(f"| {b} | {b_is.get(b, 0)} | {b_oos.get(b, 0)} |")
        lines.append("")

        m_is = _get(payload, tf, "IS", "mfe_mae") or {}
        m_oos = _get(payload, tf, "OOS", "mfe_mae") or {}
        lines.append("### MFE thresholds (share of trades)")
        lines.append("| metric | IS | OOS |")
        lines.append("| --- | ---: | ---: |")
        for k, label in (
            ("pct_reach_0p5r_before_exit", "Reach +0.5R before exit"),
            ("pct_reach_1r_before_exit", "Reach +1R before exit"),
            ("pct_reach_1p5r_before_exit", "Reach +1.5R before exit"),
            ("median_mfe_losing_trades_r", "Median MFE (losers, R)"),
            ("pct_sl_within_2_bars_after_fill", "SL within 2 bars after fill"),
        ):
            vi, vo = m_is.get(k), m_oos.get(k)
            if vi is not None and vo is not None:
                lines.append(f"| {label} | {vi:.1%} | {vo:.1%} |" if "pct_" in k else f"| {label} | {vi:.3f} | {vo:.3f} |")
        lines.append("")

        w_is = _get(payload, tf, "IS", "whatif") or []
        w_oos = _get(payload, tf, "OOS", "whatif") or []
        if w_is or w_oos:
            lines.append("### What-if exits (same fills)")
            lines.append("| TP R | SL× | max hold | gross E IS | net E IS | gross E OOS | net E OOS |")
            lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            index_oos = {(r["tp_r"], r["sl_mult"], r["max_hold"]): r for r in w_oos}
            for r in w_is:
                key = (r["tp_r"], r["sl_mult"], r["max_hold"])
                o = index_oos.get(key, {})
                lines.append(
                    f"| {r['tp_r']} | {r['sl_mult']} | {r['max_hold']} | "
                    f"{r.get('expectancy_gross_r', 0):.3f} | {r.get('expectancy_net_r', 0):.3f} | "
                    f"{o.get('expectancy_gross_r', 0):.3f} | {o.get('expectancy_net_r', 0):.3f} |"
                )
            lines.append("")

        f_is = _get(payload, tf, "IS", "fees") or []
        f_oos = _get(payload, tf, "OOS", "fees") or []
        if f_is or f_oos:
            lines.append("### Fee scenarios")
            lines.append("| scenario | gross E IS | net E IS | net E OOS |")
            lines.append("| --- | ---: | ---: | ---: |")
            oos_map = {r["scenario"]: r for r in f_oos}
            for r in f_is:
                o = oos_map.get(r["scenario"], {})
                lines.append(
                    f"| {r['scenario']} | {r.get('expectancy_gross_r', 0):.3f} | "
                    f"{r.get('expectancy_net_r', 0):.3f} | {o.get('expectancy_net_r', 0):.3f} |"
                )
            lines.append("")
    return "\n".join(lines)


def export_reports(run_dir: Path, console_log: Path | None = None) -> None:
    """Copy summary + diagnostics into reports/ (no secrets, no parquet)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_run = run_dir / "summary.txt"
    diag_run = run_dir / "diagnostics.json"
    if summary_run.exists():
        shutil.copy2(summary_run, REPORTS_DIR / "phase34_btc_summary.txt")
    if diag_run.exists():
        shutil.copy2(diag_run, REPORTS_DIR / "phase34_btc_diagnostics.json")
        payload = json.loads(diag_run.read_text(encoding="utf-8"))
        (REPORTS_DIR / "phase34_whatif.md").write_text(build_whatif_markdown(payload), encoding="utf-8")
    src = console_log or (REPO_ROOT / "data" / "backtest" / "phase34_run_console.txt")
    if src.exists():
        shutil.copy2(src, REPORTS_DIR / "phase34_console.txt")