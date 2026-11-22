"""Phase 3.5c — predictive tests with clean IS→OOS protocol."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.paths import REPO_ROOT
from backtest.split import filter_sample
from research.coverage import run_coverage
from research.coverage import table_markdown as coverage_md
from research.features import build_feature_table, feature_columns
from research.rule_backtest import rule_summary, run_rule_backtest, thresholds_from_is
from research.selection_rules import SELECTION_RULE_MD, is_selection_eligible
from research.targets import add_forward_targets

REPORTS_DIR = REPO_ROOT / "reports"
PHASE_TAG = "35c"
IC_TSTAT_MIN = 3.0
SIGN_MONTHS_MIN = 0.70
MIN_OOS_TRADES = 100
HORIZONS = (1, 4, 12, 24)
TARGET_SUFFIX = "fwd_net_low"
OOS_ALREADY_SEEN = re.compile(r"(taker_|above_ema|realized_vol|atr_pct|weekday|setup_score|has_)", re.I)


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _month_key(ms: int) -> str:
    t = pd.to_datetime(ms, unit="ms", utc=True)
    return f"{t.year:04d}-{t.month:02d}"


def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    return a.rank(method="average").corr(b.rank(method="average"))


def monthly_ic(feature: pd.Series, target: pd.Series, months: pd.Series) -> tuple[float, float, float]:
    rows: list[float] = []
    for mo in sorted(months.dropna().unique()):
        mask = months == mo
        f = feature[mask]
        y = target[mask]
        if len(f) < 30 or f.nunique() < 2:
            continue
        ic = _spearman(f, y)
        if ic is not None and np.isfinite(ic):
            rows.append(float(ic))
    if len(rows) < 3:
        return 0.0, 0.0, 0.0
    arr = np.array(rows)
    mean = float(arr.mean())
    tstat = float(mean / (arr.std(ddof=1) / np.sqrt(len(arr)))) if arr.std(ddof=1) > 0 else 0.0
    sign = float((np.sign(arr) == np.sign(mean)).mean()) if mean != 0 else 0.5
    return mean, tstat, sign


def run_ic_table(df: pd.DataFrame, features: list[str], n_tested: int) -> pd.DataFrame:
    months = df["close_time"].map(_month_key)
    rows: list[dict] = []
    for feat in features:
        for h in HORIZONS:
            tgt = f"{TARGET_SUFFIX}_{h}"
            if tgt not in df.columns:
                continue
            mean_ic, tstat, sign_pct = monthly_ic(df[feat], df[tgt], months)
            rows.append(
                {
                    "feature": feat,
                    "horizon": h,
                    "mean_ic": mean_ic,
                    "ic_tstat": tstat,
                    "ic_sign_pct": sign_pct,
                    "likely_noise": abs(tstat) < IC_TSTAT_MIN,
                    "n_features_tested": n_tested,
                    "oos_already_seen": bool(OOS_ALREADY_SEEN.search(feat)),
                }
            )
    return pd.DataFrame(rows)


def _df_to_md(table: pd.DataFrame, max_rows: int | None = 80) -> str:
    if table.empty:
        return "_empty_"
    sub = table if max_rows is None else table.head(max_rows)
    cols = list(sub.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in sub.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, (float, np.floating)) and c not in ("horizon", "n_features_tested", "n_unique"):
                cells.append(f"{v:.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def selection_paths(symbol: str) -> tuple[Path, Path]:
    sym = symbol.upper()
    return (
        REPORTS_DIR / f"phase{PHASE_TAG}_{sym}_is_selection.md",
        REPORTS_DIR / f"phase{PHASE_TAG}_{sym}_is_selection.json",
    )


def assert_frozen_for_oos(symbols: list[str]) -> None:
    missing: list[str] = []
    for sym in symbols:
        _, jp = selection_paths(sym)
        if not jp.exists():
            missing.append(str(jp))
    if missing:
        raise SystemExit(f"Missing frozen IS selection: {missing}. Run --phase is first.")
    tracked = [str(selection_paths(s)[1].relative_to(REPO_ROOT)) for s in symbols]
    porcelain = subprocess.check_output(["git", "status", "--porcelain", *tracked], text=True).strip()
    if porcelain:
        raise SystemExit(
            "IS selection files are not committed. Commit with message including "
            "'IS selection frozen' before --phase oos.\n" + porcelain
        )


def pick_qualified(ic_is: pd.DataFrame, is_df: pd.DataFrame, symbol: str, cfg: BacktestConfig) -> list[dict]:
    ic_is = ic_is.sort_values("ic_tstat", key=abs, ascending=False)
    picks: list[dict] = []
    seen: set[str] = set()
    for _, row in ic_is.iterrows():
        if len(picks) >= 5:
            break
        feat = str(row["feature"])
        if not is_selection_eligible(feat):
            continue
        if feat in seen:
            continue
        if abs(float(row["ic_tstat"])) < IC_TSTAT_MIN:
            continue
        if float(row["ic_sign_pct"]) < SIGN_MONTHS_MIN:
            continue
        h = int(row["horizon"])
        thr = thresholds_from_is(is_df[feat])
        if thr is None:
            continue
        tr_low = run_rule_backtest(
            is_df, feat, h, symbol, thresholds=thr, ic_mean=float(row["mean_ic"]), cfg=cfg, low_fee=True
        )
        summ = rule_summary(tr_low)
        if summ.get("trades", 0) < 10 or summ.get("net_e_pct", 0) <= 0:
            continue
        seen.add(feat)
        picks.append(
            {
                "feature": feat,
                "horizon": h,
                "mean_ic": float(row["mean_ic"]),
                "ic_tstat": float(row["ic_tstat"]),
                "ic_sign_pct": float(row["ic_sign_pct"]),
                "is_rule_net_e_pct_low_fee": float(summ.get("net_e_pct", 0)),
                "is_rule_trades": int(summ.get("trades", 0)),
                "oos_already_seen": bool(row.get("oos_already_seen")),
            }
        )
    return picks


def write_is_selection(symbol: str, picks: list[dict]) -> None:
    md_path, json_path = selection_paths(symbol)
    if not picks:
        body = "\n".join(
            [
                f"# Phase 3.5c IS selection — {symbol}",
                "",
                f"timestamp: {datetime.now(tz=UTC).isoformat()}",
                f"commit: `{_git_hash()}`",
                "",
                SELECTION_RULE_MD,
                "",
                "## NO FEATURE QUALIFIES",
                "",
            ]
        )
    else:
        body = "\n".join(
            [
                f"# Phase 3.5c IS selection — {symbol}",
                "",
                f"timestamp: {datetime.now(tz=UTC).isoformat()}",
                f"commit: `{_git_hash()}`",
                "",
                SELECTION_RULE_MD,
                "",
                "| feature | horizon | IC t | sign months | IS net E% (low fee) | trades | note |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
            + [
                f"| {p['feature']} | {p['horizon']} | {p['ic_tstat']:.2f} | {p['ic_sign_pct']:.0%} | "
                f"{p['is_rule_net_e_pct_low_fee']:.3f} | {p['is_rule_trades']} | "
                f"{'OOS already seen' if p['oos_already_seen'] else ''} |"
                for p in picks
            ]
        )
    md_path.write_text(body, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"symbol": symbol, "picks": picks, "git": _git_hash(), "ts": datetime.now(tz=UTC).isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )


def _oos_trade_count(picks: list[dict], oos_rule: dict[str, dict]) -> int:
    return sum(int(oos_rule.get(p["feature"], {}).get("low_fee", {}).get("trades", 0) or 0) for p in picks)


def symbol_verdict(picks: list[dict], oos_rule: dict[str, dict]) -> str:
    if not picks:
        return "noise"
    if _oos_trade_count(picks, oos_rule) < MIN_OOS_TRADES:
        return "insufficient OOS trades"
    pos = [p for p in picks if oos_rule.get(p["feature"], {}).get("net_e_pct", -1) > 0]
    if len(pos) >= 2:
        return "tradeable edge after costs"
    if len(pos) == 1:
        return "weak"
    return "noise"


def run_is(symbol: str, cfg: BacktestConfig) -> dict[str, Any]:
    df = add_forward_targets(build_feature_table(symbol, cfg=cfg), cfg)
    feats = feature_columns(df)
    is_df = filter_sample(df, "IS")
    ic_is = run_ic_table(is_df, feats, len(feats) * len(HORIZONS))
    picks = pick_qualified(ic_is, is_df, symbol, cfg)
    write_is_selection(symbol, picks)
    return {"symbol": symbol, "ic_is": ic_is, "picks": picks}


def run_oos(symbol: str, cfg: BacktestConfig) -> dict[str, Any]:
    _, jp = selection_paths(symbol)
    payload = json.loads(jp.read_text(encoding="utf-8"))
    picks = payload.get("picks", [])
    df = add_forward_targets(build_feature_table(symbol, cfg=cfg), cfg)
    is_df = filter_sample(df, "IS")
    oos_df = filter_sample(df, "OOS")
    feats = feature_columns(df)
    ic_is = run_ic_table(is_df, feats, len(feats) * len(HORIZONS))
    ic_oos = run_ic_table(oos_df, feats, len(feats) * len(HORIZONS))
    rule_rows: dict[str, dict] = {}
    oos_trades: list[pd.DataFrame] = []
    for p in picks:
        feat, h = p["feature"], int(p["horizon"])
        row = ic_is[(ic_is.feature == feat) & (ic_is.horizon == h)].iloc[0]
        thr = thresholds_from_is(is_df[feat])
        if thr is None:
            continue
        tr_std = run_rule_backtest(
            oos_df, feat, h, symbol, thresholds=thr, ic_mean=float(row["mean_ic"]), cfg=cfg, low_fee=False
        )
        tr_low = run_rule_backtest(
            oos_df, feat, h, symbol, thresholds=thr, ic_mean=float(row["mean_ic"]), cfg=cfg, low_fee=True
        )
        rule_rows[feat] = {
            "conservative": rule_summary(tr_std),
            "low_fee": rule_summary(tr_low),
            "net_e_pct": rule_summary(tr_low).get("net_e_pct", 0),
        }
        oos_trades.append(tr_low)
    return {
        "symbol": symbol,
        "picks": picks,
        "ic_is": ic_is,
        "ic_oos": ic_oos,
        "rule_oos": rule_rows,
        "verdict": symbol_verdict(picks, rule_rows),
    }


def build_final_report(coverage_table: pd.DataFrame, is_results: list[dict], oos_results: list[dict] | None) -> str:
    lines = [
        "# Phase 3.5c — Edge research",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()} | commit `{_git_hash()}`_",
        "",
        SELECTION_RULE_MD,
        "",
        "## Coverage summary",
        "",
        coverage_md(coverage_table) if not coverage_table.empty else "_no coverage_",
        "",
    ]
    for block in is_results:
        sym = block["symbol"]
        lines.append(f"## {sym} — IS (all features)")
        lines.append("")
        lines.append(_df_to_md(block["ic_is"], None))
        lines.append("")
    if oos_results:
        lines.append("## OOS confirmation")
        lines.append("")
        for block in oos_results:
            sym = block["symbol"]
            lines.append(f"### {sym}")
            lines.append("")
            if not block["picks"]:
                lines.append("_NO FEATURE QUALIFIES (IS)_")
            else:
                for p in block["picks"]:
                    note = " *(OOS already seen in Phase 3.5 — treat cautiously)*" if p.get("oos_already_seen") else ""
                    lines.append(f"- `{p['feature']}` horizon {p['horizon']}{note}")
                    ro = block["rule_oos"].get(p["feature"], {})
                    for tag in ("conservative", "low_fee"):
                        s = ro.get(tag, {})
                        if s.get("trades", 0):
                            lines.append(
                                f"  - {tag}: trades={s['trades']} win={s['win_rate']:.1%} "
                                f"net_E%={s.get('net_e_pct', 0):.3f} PF={s.get('profit_factor', 0):.2f}"
                            )
            lines.append("")
            lines.append(f"**Verdict ({sym})**: {block['verdict']}")
            lines.append("")
    return "\n".join(lines)


def run_pipeline(symbols: list[str], phase: str) -> None:
    cfg = BacktestConfig()
    cov_table, cov_fails = run_coverage(symbols)
    (REPORTS_DIR / f"phase{PHASE_TAG}_coverage.md").write_text(coverage_md(cov_table), encoding="utf-8")
    deriv_fail = [f for f in cov_fails if any(d in f for d in ("funding", "open_interest", "basis", "ls_ratio", "oi_"))]
    if deriv_fail:
        print("WARN derivative coverage failures:", deriv_fail[:10])

    is_results: list[dict] = []
    oos_results: list[dict] | None = None

    if phase in ("is", "all"):
        for sym in symbols:
            is_results.append(run_is(sym, cfg))
        print(f"Wrote per-symbol IS selection under reports/phase{PHASE_TAG}_*_is_selection.*")
        if phase == "is":
            sections = build_final_report(cov_table, is_results, None)
            (REPORTS_DIR / f"phase{PHASE_TAG}_edge_research.md").write_text(sections, encoding="utf-8")
            return

    if phase in ("oos", "all"):
        if phase == "oos":
            assert_frozen_for_oos(symbols)
        oos_results = []
        for sym in symbols:
            oos_results.append(run_oos(sym, cfg))
        oos_md = ["# Phase 3.5c OOS confirmation", "", f"_commit `{_git_hash()}`_", ""]
        for block in oos_results:
            oos_md.append(f"## {block['symbol']}: **{block['verdict']}**")
            oos_md.append(_df_to_md(block["ic_oos"], 30))
            oos_md.append("")
        (REPORTS_DIR / f"phase{PHASE_TAG}_oos.md").write_text("\n".join(oos_md), encoding="utf-8")
        report = build_final_report(cov_table, is_results, oos_results)
        (REPORTS_DIR / f"phase{PHASE_TAG}_edge_research.md").write_text(report, encoding="utf-8")
        print(f"Wrote {REPORTS_DIR / f'phase{PHASE_TAG}_edge_research.md'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Phase 3.5c edge research")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--phase", default="all", choices=("is", "oos", "all"))
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    run_pipeline(symbols, args.phase)


if __name__ == "__main__":
    main()