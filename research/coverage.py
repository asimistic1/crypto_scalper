"""Feature coverage report — must PASS before IC tests (Phase 3.5b)."""

from __future__ import annotations

import argparse

import pandas as pd

from backtest.config import BacktestConfig
from backtest.paths import REPO_ROOT
from backtest.split import filter_sample
from research.features import DERIVATIVES_FEATURES, build_feature_table, feature_columns

REPORTS_DIR = REPO_ROOT / "reports"
MIN_NON_NULL = 0.90
MIN_UNIQUE = 20


def coverage_rows(symbol: str, df: pd.DataFrame, feats: list[str], sample: str) -> tuple[list[dict], list[str]]:
    blk = filter_sample(df, sample) if sample != "ALL" else df
    failures: list[str] = []
    rows: list[dict] = []
    for feat in feats:
        if feat not in blk.columns:
            rows.append(
                {
                    "symbol": symbol,
                    "sample": sample,
                    "feature": feat,
                    "non_null_pct": 0.0,
                    "n_unique": 0,
                    "min": "",
                    "median": "",
                    "max": "",
                    "first_ts": "",
                    "last_ts": "",
                    "status": "FAIL",
                }
            )
            if feat in DERIVATIVES_FEATURES:
                failures.append(f"{symbol} {feat}: missing column")
            continue
        s = blk[feat]
        valid = s.dropna()
        nn = float(s.notna().mean()) if len(s) else 0.0
        nu = int(valid.nunique()) if len(valid) else 0
        t0, t1 = "", ""
        mask = s.notna()
        if mask.any():
            ct = blk.loc[mask, "close_time"]
            t0 = pd.to_datetime(int(ct.min()), unit="ms", utc=True).isoformat()
            t1 = pd.to_datetime(int(ct.max()), unit="ms", utc=True).isoformat()
        status = "PASS"
        if nn < MIN_NON_NULL or nu < MIN_UNIQUE:
            status = "FAIL"
            if feat in DERIVATIVES_FEATURES or nn < MIN_NON_NULL or nu < MIN_UNIQUE:
                failures.append(f"{symbol} {feat}: non_null={nn:.1%} unique={nu}")
        rows.append(
            {
                "symbol": symbol,
                "sample": sample,
                "feature": feat,
                "non_null_pct": nn,
                "n_unique": nu,
                "min": float(valid.min()) if len(valid) else "",
                "median": float(valid.median()) if len(valid) else "",
                "max": float(valid.max()) if len(valid) else "",
                "first_ts": t0,
                "last_ts": t1,
                "status": status,
            }
        )
    return rows, failures


def run_coverage(symbols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    cfg = BacktestConfig()
    all_rows: list[dict] = []
    all_fail: list[str] = []
    for sym in symbols:
        df = build_feature_table(sym, cfg=cfg)
        feats = feature_columns(df)
        for sample in ("IS", "ALL"):
            rows, fails = coverage_rows(sym, df, feats, sample)
            all_rows.extend(rows)
            for f in fails:
                if sample == "IS":
                    all_fail.append(f)
    table = pd.DataFrame(all_rows)
    return table, all_fail


def table_markdown(df: pd.DataFrame) -> str:
    lines = [
        "# Phase 3.5b — Feature coverage",
        "",
        f"PASS thresholds: ≥{MIN_NON_NULL:.0%} non-null, ≥{MIN_UNIQUE} unique values (IS).",
        "",
        "| symbol | sample | feature | non_null | unique | min | median | max | first | last | status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['symbol']} | {r['sample']} | {r['feature']} | {100*r['non_null_pct']:.1f}% | {r['n_unique']} | "
            f"{r['min']} | {r['median']} | {r['max']} | {r['first_ts'][:10] if r['first_ts'] else ''} | "
            f"{r['last_ts'][:10] if r['last_ts'] else ''} | {r['status']} |"
        )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Feature coverage report")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--strict", action="store_true", help="Exit 1 if any IS derivative FAIL")
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    table, fails = run_coverage(symbols)
    path = REPORTS_DIR / "phase35b_coverage.md"
    path.write_text(table_markdown(table), encoding="utf-8")
    print(table_markdown(table)[:2000])
    print(f"\nWrote {path}")
    if fails:
        print("FAILURES (IS):")
        for f in fails:
            print(" -", f)
    deriv_fail = [f for f in fails if f.split(maxsplit=2)[1] in DERIVATIVES_FEATURES]
    if args.strict and deriv_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()