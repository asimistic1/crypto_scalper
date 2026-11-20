"""
Walk closed LTF bars and summarize build_setup outcomes (no look-ahead).

Usage: python tools/signal_funnel.py BTCUSDT 15m
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.candle_store import get_many  # noqa: E402
from core.config import HIGHER_TIMEFRAMES, MIN_24H_QUOTE_VOLUME_USDT  # noqa: E402
from core.exchange_info import price_precision, tick_size  # noqa: E402
from core.models import Direction  # noqa: E402
from core.security import validate_symbol_rest  # noqa: E402
from core.setup_builder import build_setup  # noqa: E402


def _as_of_from_close_time(close_ms: int) -> datetime:
    return pd.to_datetime(close_ms, unit="ms", utc=True).to_pydatetime()


def _outcome_label(setup) -> str:
    if setup.direction == Direction.LONG:
        return "LONG"
    if setup.direction == Direction.SHORT:
        return "SHORT"
    for r in setup.reasons:
        if r.startswith("✖"):
            return r
    return "NO_TRADE"


def run_funnel(symbol: str, timeframe: str, *, walk_bars: int = 500) -> None:
    ok, msg = validate_symbol_rest(symbol)
    if not ok:
        print(msg)
        sys.exit(1)

    htf_tfs = HIGHER_TIMEFRAMES.get(timeframe, ())
    all_tfs = (timeframe, *htf_tfs, "1d")
    frames = get_many(symbol.upper(), all_tfs)

    ltf = frames[timeframe].df
    if ltf.empty:
        print("No LTF data")
        sys.exit(1)

    for tf, fr in frames.items():
        if fr.stale:
            print(f"Warning: {tf} data marked stale")

    tick = float(tick_size(symbol))
    quote_vol = MIN_24H_QUOTE_VOLUME_USDT * 2
    htf_dfs = {tf: frames[tf].df for tf in htf_tfs if tf in frames}
    daily = frames["1d"].df if frames.get("1d") else None

    n = len(ltf)
    start = max(0, n - walk_bars)
    counts: Counter[str] = Counter()
    scores: list[float] = []
    first_t: datetime | None = None
    last_t: datetime | None = None

    for i in range(start, n):
        row = ltf.iloc[i]
        as_of = _as_of_from_close_time(int(row["close_time"]))
        if first_t is None:
            first_t = as_of
        last_t = as_of

        setup = build_setup(
            symbol.upper(),
            timeframe,
            ltf,
            htf_dfs,
            daily,
            as_of,
            tick,
            quote_vol,
        )
        key = _outcome_label(setup)
        counts[key] += 1
        if setup.direction in (Direction.LONG, Direction.SHORT):
            scores.append(float(setup.score))

    days = 1.0
    if first_t and last_t:
        days = max((last_t - first_t).total_seconds() / 86_400.0, 1e-6)

    setups = counts.get("LONG", 0) + counts.get("SHORT", 0)
    avg_score = sum(scores) / len(scores) if scores else 0.0

    print(f"\nSignal funnel — {symbol.upper()} {timeframe} (last {n - start} closed bars)")
    print(f"Price precision: {price_precision(symbol)} · tick {tick}")
    print("-" * 60)
    for key, cnt in counts.most_common():
        print(f"  {cnt:5d}  {key}")
    print("-" * 60)
    print(f"  Setups (LONG+SHORT): {setups}")
    print(f"  Setups per day (approx): {setups / days:.2f}")
    print(f"  Average setup score: {avg_score:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal funnel diagnostic")
    parser.add_argument("symbol", help="REST symbol e.g. BTCUSDT")
    parser.add_argument("timeframe", choices=("5m", "15m", "1h"))
    parser.add_argument("--bars", type=int, default=500)
    args = parser.parse_args()
    run_funnel(args.symbol, args.timeframe, walk_bars=args.bars)


if __name__ == "__main__":
    main()