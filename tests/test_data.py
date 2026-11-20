"""
Quick sanity checks for Binance candle + ticker fetching.
Run from project root: python tests/test_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from project root when running this file directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from core.data import get_candles, get_ticker

SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "15m"
LIMIT = 50


def main() -> int:
    failures: list[str] = []

    df, err = get_candles(SYMBOL, TIMEFRAME, limit=LIMIT)
    if err:
        print(f"FAILED: get_candles error: {err}")
        return 1
    if df is None or df.empty:
        print("FAILED: empty dataframe")
        return 1

    print("Last 5 candle rows:")
    print(df.tail(5).to_string(index=False))

    ticker, terr = get_ticker(SYMBOL)
    print("\nTicker:", ticker if not terr else f"error: {terr}")

    required = ["time", "open", "high", "low", "close", "volume", "is_closed"]
    for col in required:
        if col not in df.columns:
            failures.append(f"missing column: {col}")

    if df[required].isnull().any().any():
        failures.append("found NaN values in OHLCV columns")

    if not df["time"].is_monotonic_increasing:
        failures.append("time column is not strictly increasing")

    bad_hl = df["high"] < df["low"]
    if bad_hl.any():
        failures.append(f"high < low on {bad_hl.sum()} rows")

    bad_high = (df["high"] < df["open"]) | (df["high"] < df["close"])
    if bad_high.any():
        failures.append(f"high below open/close on {bad_high.sum()} rows")

    bad_low = (df["low"] > df["open"]) | (df["low"] > df["close"])
    if bad_low.any():
        failures.append(f"low above open/close on {bad_low.sum()} rows")

    if failures:
        print("\nCHECKS FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())