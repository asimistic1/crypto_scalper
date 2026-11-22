"""Phase 3.5 — predictive power tests (IS exploration, OOS confirmation)."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.history import ensure_indicators, load_history
from backtest.metrics import core_metrics
from backtest.paths import REPO_ROOT
from backtest.simulator import SimSignal, simulate_trade, trade_to_dict
from backtest.split import filter_sample
from core.models import Direction, EntryType
from research.features import build_feature_table, feature_columns
from research.targets import add_forward_targets

REPORTS_DIR = REPO_ROOT / "reports"
IC_TSTAT_FLAG = 3.0
HORIZONS = (1, 4, 12, 24)
TARGET_SUFFIX = "fwd_net_low"


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


def quintile_spread(feature: pd.Series, target: pd.Series) -> dict[str, float]:
    valid = feature.notna() & target.notna()
    f = feature[valid]
    y = target[valid]
    if len(f) < 50:
        return {}
    try:
        q = pd.qcut(f.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    except ValueError:
        return {}
    means = y.groupby(q, observed=False).mean()
    return {f"q{k}": float(means.get(k, np.nan)) for k in range(1, 6)} | {
        "top_minus_bottom": float(means.get(5, np.nan) - means.get(1, np.nan))
    }


def _rule_trades(
    df: pd.DataFrame,
    feature: str,
    horizon: int,
    cfg: BacktestConfig,
    symbol: str,
) -> pd.DataFrame:
    """Top quintile long / bottom short, fixed hold; ATR-based 1R stop."""
    ind = ensure_indicators(load_history(symbol, "1h"))
    atr = ind["atr_14"].to_numpy(dtype=float) if "atr_14" in ind.columns else ind["close"].to_numpy() * 0.005
    ct = ind["close_time"].to_numpy(dtype=np.int64)
    f = df[feature]
    try:
        quint = pd.qcut(f.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    except ValueError:
        return pd.DataFrame()
    rows: list[dict] = []
    busy = -1
    for i in range(50, len(df) - horizon - 2):
        if i <= busy:
            continue
        raw_q = quint.iloc[i]
        if pd.isna(raw_q):
            continue
        qv = int(raw_q)
        if qv == 5:
            direction = Direction.LONG
        elif qv == 1:
            direction = Direction.SHORT
        else:
            continue
        bar_i = int(np.searchsorted(ct, int(df["close_time"].iloc[i]), side="right")) - 1
        if bar_i < 0 or bar_i + 1 >= len(ind):
            continue
        entry_i = bar_i + 1
        entry = float(ind.iloc[entry_i]["open"])
        r = float(atr[bar_i])
        if r <= 0:
            continue
        sl = entry - r if direction == Direction.LONG else entry + r
        sim = SimSignal(
            direction=direction,
            entry_type=EntryType.MARKET,
            entry=entry,
            stop_loss=sl,
            tp1=entry + r if direction == Direction.LONG else entry - r,
            tp2=entry + 2 * r if direction == Direction.LONG else entry - 2 * r,
            tp3=entry + 3 * r if direction == Direction.LONG else entry - 3 * r,
            signal_bar=entry_i - 1,
            strategy="edge_rule",
            score=60.0,
            setup_id=f"edge_{i}",
        )
        hold_cfg = BacktestConfig(
            max_hold_bars={**cfg.max_hold_bars, "1h": horizon},
            taker_fee=cfg.taker_fee,
            maker_fee=cfg.maker_fee,
            slippage=cfg.slippage,
            fee_model=cfg.fee_model,
            low_fee_taker=cfg.low_fee_taker,
            low_fee_maker=cfg.low_fee_maker,
        )
        trade = simulate_trade(
            ind, sim, hold_cfg, exit_model="tp1_full", symbol=symbol, timeframe="1h"
        )
        d = trade_to_dict(trade)
        d["close_time"] = int(df["close_time"].iloc[i])
        rows.append(d)
        busy = entry_i + horizon
    return pd.DataFrame(rows)


def run_ic_table(is_df: pd.DataFrame, features: list[str], n_tested: int) -> pd.DataFrame:
    months = is_df["close_time"].map(_month_key)
    rows: list[dict] = []
    for feat in features:
        for h in HORIZONS:
            tgt = f"{TARGET_SUFFIX}_{h}"
            if tgt not in is_df.columns:
                continue
            mean_ic, tstat, sign_pct = monthly_ic(is_df[feat], is_df[tgt], months)
            rows.append(
                {
                    "feature": feat,
                    "horizon": h,
                    "mean_ic": mean_ic,
                    "ic_tstat": tstat,
                    "ic_sign_pct": sign_pct,
                    "likely_noise": abs(tstat) < IC_TSTAT_FLAG,
                    "n_features_tested": n_tested,
                }
            )
    return pd.DataFrame(rows)


def pick_top_features(ic_df: pd.DataFrame, k: int = 5) -> list[tuple[str, int]]:
    if ic_df.empty:
        return []
    ic_df = ic_df.sort_values("ic_tstat", key=abs, ascending=False)
    seen: set[str] = set()
    picked: list[tuple[str, int]] = []
    for _, row in ic_df.iterrows():
        f = str(row["feature"])
        if f in seen:
            continue
        seen.add(f)
        picked.append((f, int(row["horizon"])))
        if len(picked) >= k:
            break
    return picked


def correlation_matrix(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    cols = [f for f in features if f in df.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    ranked = df[cols].rank()
    return ranked.corr()


def verdict_row(mean_ic: float, tstat: float, quintile_spread_val: float, cost_rt: float) -> str:
    if abs(tstat) < IC_TSTAT_FLAG:
        return "noise"
    if quintile_spread_val > cost_rt and mean_ic * quintile_spread_val > 0:
        return "predictive after costs"
    return "weak"


def _df_to_md(table: pd.DataFrame, max_rows: int = 50) -> str:
    if table.empty:
        return "_empty_"
    sub = table.head(max_rows)
    cols = list(sub.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in sub.iterrows():
        cells = [f"{row[c]:.4f}" if isinstance(row[c], (float, np.floating)) else str(row[c]) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_markdown(
    symbol: str,
    is_ic: pd.DataFrame,
    oos_ic: pd.DataFrame,
    quintile_is: dict[str, Any],
    quintile_oos: dict[str, Any],
    rules_is: pd.DataFrame,
    rules_oos: pd.DataFrame,
    corr: pd.DataFrame,
    n_features: int,
    cost_rt: float,
) -> str:
    lines = [
        f"# Phase 3.5 — Edge research ({symbol})",
        "",
        f"Generated {datetime.now(tz=UTC).isoformat()} | features tested: **{n_features}** "
        f"(|t| < {IC_TSTAT_FLAG} flagged as likely noise)",
        "",
        "## IS selection (exploration)",
        "",
    ]
    if not is_ic.empty:
        lines.append(_df_to_md(is_ic, 40))
    lines.append("")
    lines.append("## OOS confirmation (single pass)")
    lines.append("")
    if not oos_ic.empty:
        lines.append(_df_to_md(oos_ic, 40))
    lines.append("")
    lines.append("## Quintile spreads vs round-trip cost (low-fee)")
    lines.append(f"Round-trip cost fraction used: **{cost_rt:.4f}**")
    for phase, block in (("IS", quintile_is), ("OOS", quintile_oos)):
        lines.append(f"\n### {phase}")
        for feat, spreads in block.items():
            sp = spreads.get("top_minus_bottom", 0.0)
            lines.append(f"- **{feat}**: top-bottom {sp:.4f}")
    lines.append("")
    lines.append("## Simple rule backtests (top/bottom quintile)")
    for name, frame in (("IS", rules_is), ("OOS", rules_oos)):
        lines.append(f"\n### {name}")
        if frame.empty:
            lines.append("_no trades_")
            continue
        m = core_metrics(frame[frame["filled"]], raw_signals=len(frame))
        lines.append(
            f"- trades={m.get('trades', 0)} win_rate={m.get('win_rate', 0):.2%} "
            f"net_E={m.get('expectancy_r', m.get('expectancy_net_r', 0)):.4f} "
            f"PF={m.get('profit_factor', 0):.2f}"
        )
    if not corr.empty:
        lines.append("\n## Spearman correlation (top features)")
        lines.append(_df_to_md(corr.round(3)))
    lines.append("\n## Plain-English verdicts")
    for _, row in is_ic.drop_duplicates("feature").iterrows():
        f = row["feature"]
        sp = quintile_is.get(f, {}).get("top_minus_bottom", 0.0)
        v = verdict_row(float(row["mean_ic"]), float(row["ic_tstat"]), sp, cost_rt)
        lines.append(f"- **{f}**: {v}")
    return "\n".join(lines)


def run_symbol(symbol: str, *, phase: str = "all") -> None:
    cfg = BacktestConfig()
    df = build_feature_table(symbol, cfg=cfg)
    df = add_forward_targets(df, cfg)
    feats = feature_columns(df)
    is_df = filter_sample(df, "IS")
    oos_df = filter_sample(df, "OOS")
    is_ic = run_ic_table(is_df, feats, len(feats) * len(HORIZONS))
    cost_rt = 2 * (cfg.low_fee_taker + cfg.slippage)

    quintile_is: dict[str, Any] = {}
    quintile_oos: dict[str, Any] = {}
    selection_path = REPORTS_DIR / "phase35_is_selection.md"

    if phase in ("all", "is"):
        for feat in feats:
            for h in HORIZONS:
                tgt = f"{TARGET_SUFFIX}_{h}"
                quintile_is[feat] = quintile_spread(is_df[feat], is_df[tgt])
        picks = pick_top_features(is_ic)
        selection_path.write_text(
            "\n".join(
                [
                    "# Phase 3.5 IS selection (frozen)",
                    "",
                    f"timestamp: {datetime.now(tz=UTC).isoformat()}",
                    f"commit: `{_git_hash()}`",
                    f"symbol: {symbol}",
                    "",
                    "## Selected rules",
                    "",
                ]
                + [f"- feature `{f}` horizon {h} bars" for f, h in picks]
                + ["", "_Do not change after viewing OOS._"]
            ),
            encoding="utf-8",
        )
        (REPORTS_DIR / "phase35_is_selection.json").write_text(
            json.dumps({"picks": picks, "git": _git_hash(), "ts": datetime.now(tz=UTC).isoformat()}, indent=2),
            encoding="utf-8",
        )

    if phase == "is":
        return "\n".join(
            [
                f"## {symbol}",
                "",
                "_IS selection frozen; run with `--phase all` for OOS confirmation._",
                "",
            ]
        )

    if selection_path.exists():
        picks = json.loads((REPORTS_DIR / "phase35_is_selection.json").read_text(encoding="utf-8")).get("picks", [])
    else:
        picks = pick_top_features(is_ic)

    for feat in feats:
        for h in HORIZONS:
            tgt = f"{TARGET_SUFFIX}_{h}"
            quintile_oos[feat] = quintile_spread(oos_df[feat], oos_df[tgt])

    oos_ic = run_ic_table(oos_df, feats, len(feats) * len(HORIZONS))

    rule_rows_is: list[pd.DataFrame] = []
    rule_rows_oos: list[pd.DataFrame] = []
    for feat, h in picks:
        rule_rows_is.append(_rule_trades(is_df, feat, h, cfg, symbol))
        rule_rows_oos.append(_rule_trades(oos_df, feat, h, cfg, symbol))
    rules_is = pd.concat(rule_rows_is, ignore_index=True) if rule_rows_is else pd.DataFrame()
    rules_oos = pd.concat(rule_rows_oos, ignore_index=True) if rule_rows_oos else pd.DataFrame()
    corr = correlation_matrix(is_df, [f for f, _ in picks])

    body = build_markdown(
        symbol, is_ic, oos_ic, quintile_is, quintile_oos, rules_is, rules_oos, corr, len(feats), cost_rt
    )
    return body.replace(f"# Phase 3.5 — Edge research ({symbol})", f"## {symbol}", 1)


def run_all(symbols: list[str], phase: str = "all") -> None:
    sections: list[str] = [
        "# Phase 3.5 — Edge research",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()} | commit `{_git_hash()}`_",
        "",
    ]
    for sym in symbols:
        sections.append(run_symbol(sym, phase=phase))
    path = REPORTS_DIR / "phase35_edge_research.md"
    path.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Phase 3.5 edge research report")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--phase", default="all", choices=("all", "is", "oos"))
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    run_all(symbols, phase=args.phase)


if __name__ == "__main__":
    main()