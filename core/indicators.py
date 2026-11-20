"""
Technical indicators using the `ta` library (TradingView-compatible defaults where possible).
"""

from __future__ import annotations

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange


def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add exponential moving averages on close: 9, 21, 50, 200.
    Column names: ema_9, ema_21, ema_50, ema_200.
    """
    out = df.copy()
    close = out["close"]
    out["ema_9"] = EMAIndicator(close=close, window=9, fillna=False).ema_indicator()
    out["ema_21"] = EMAIndicator(close=close, window=21, fillna=False).ema_indicator()
    out["ema_50"] = EMAIndicator(close=close, window=50, fillna=False).ema_indicator()
    out["ema_200"] = EMAIndicator(close=close, window=200, fillna=False).ema_indicator()
    return out


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add RSI(14) and ATR(14) — same period defaults as common TradingView presets.
    """
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]

    out["rsi_14"] = RSIIndicator(close=close, window=14, fillna=False).rsi()
    out["atr_14"] = AverageTrueRange(
        high=high, low=low, close=close, window=14, fillna=False
    ).average_true_range()
    return out