"""
Technical indicators — vectorized numpy/pandas (TradingView-style defaults).

Pure functions: input DataFrame must include columns
time, open, high, low, close, volume (time = timezone-aware or UTC).
Returns a NEW DataFrame; never mutates the input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema_tradingview(close: np.ndarray, period: int) -> np.ndarray:
    """EMA seeded with SMA of the first `period` closes (TradingView)."""
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = np.mean(close[:period])
    for i in range(period, n):
        out[i] = alpha * close[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder RMA: first value = SMA(period), then RMA recursion."""
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    if n < period:
        return out
    out[period - 1] = np.mean(values[:period])
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def _rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n <= period:
        return out
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)
    # align: gain/loss index i maps to close index i+1
    for i in range(period, n):
        g = avg_gain[i - 1]
        loss_v = avg_loss[i - 1]
        if loss_v == 0:
            out[i] = 100.0
        else:
            rs = g / loss_v
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    prev = close[:-1]
    tr[1:] = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    return tr


def _atr_wilder(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = _true_range(high, low, close)
    return _rma(tr, period)


def _macd(
    close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ema_fast = _ema_tradingview(close, fast)
    ema_slow = _ema_tradingview(close, slow)
    macd_line = ema_fast - ema_slow
    # signal on valid macd segment
    macd_sig = _ema_tradingview(np.nan_to_num(macd_line, nan=0.0), signal)
    # mask early NaN region
    start = slow - 1
    macd_sig[:start] = np.nan
    hist = macd_line - macd_sig
    return macd_line, macd_sig, hist


def _stoch_rsi(
    close: np.ndarray, rsi_len: int = 14, stoch_len: int = 14, k_smooth: int = 3, d_smooth: int = 3
) -> tuple[np.ndarray, np.ndarray]:
    rsi = _rsi_wilder(close, rsi_len)
    n = len(close)
    stoch = np.full(n, np.nan, dtype=float)
    for i in range(rsi_len + stoch_len, n):
        window = rsi[i - stoch_len + 1 : i + 1]
        lo, hi = np.nanmin(window), np.nanmax(window)
        if hi == lo:
            stoch[i] = 0.0
        else:
            stoch[i] = (rsi[i] - lo) / (hi - lo) * 100.0
    k = pd.Series(stoch).rolling(k_smooth, min_periods=k_smooth).mean().to_numpy()
    d = pd.Series(k).rolling(d_smooth, min_periods=d_smooth).mean().to_numpy()
    return k, d


def _bollinger(
    close: np.ndarray, period: int = 20, mult: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    s = pd.Series(close)
    mid = s.rolling(period, min_periods=period).mean().to_numpy()
    std = s.rolling(period, min_periods=period).std(ddof=0).to_numpy()
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid
    return upper, mid, lower, width


def _daily_vwap(time_s: pd.Series, high: np.ndarray, low: np.ndarray, close: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """VWAP reset 00:00 UTC per calendar day."""
    typical = (high + low + close) / 3.0
    t = pd.to_datetime(time_s, utc=True)
    day = t.dt.floor("D")
    df = pd.DataFrame({"day": day, "tpv": typical * vol, "vol": vol})
    cum_tpv = df.groupby("day", sort=False)["tpv"].cumsum()
    cum_vol = df.groupby("day", sort=False)["vol"].cumsum()
    return (cum_tpv / cum_vol.replace(0, np.nan)).to_numpy()


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    sign = np.sign(np.diff(close, prepend=close[0]))
    sign[0] = 0.0
    return np.cumsum(sign * volume)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add full indicator set for setup analysis.
    Requires columns: time, open, high, low, close, volume.
    """
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    out = df.copy()
    close = out["close"].to_numpy(dtype=float)
    high = out["high"].to_numpy(dtype=float)
    low = out["low"].to_numpy(dtype=float)
    vol = out["volume"].to_numpy(dtype=float)

    for period, name in ((9, "ema_9"), (21, "ema_21"), (50, "ema_50"), (200, "ema_200")):
        out[name] = _ema_tradingview(close, period)

    out["rsi_14"] = _rsi_wilder(close, 14)
    out["atr_14"] = _atr_wilder(high, low, close, 14)

    macd, macd_sig, macd_hist = _macd(close)
    out["macd"] = macd
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist

    sk, sd = _stoch_rsi(close)
    out["stochrsi_k"] = sk
    out["stochrsi_d"] = sd

    bb_u, bb_m, bb_l, bb_w = _bollinger(close)
    out["bb_upper"] = bb_u
    out["bb_mid"] = bb_m
    out["bb_lower"] = bb_l
    out["bb_width"] = bb_w

    out["vwap_daily"] = _daily_vwap(out["time"], high, low, close, vol)

    obv = _obv(close, vol)
    out["obv"] = obv
    obv_ema = _ema_tradingview(obv, 20)
    out["obv_ema_20"] = obv_ema
    out["obv_ema_slope_5"] = pd.Series(obv_ema).diff(5).to_numpy()

    vol_sma = pd.Series(vol).rolling(20, min_periods=20).mean().to_numpy()
    out["volume_sma_20"] = vol_sma
    out["volume_ratio"] = vol / vol_sma

    return out


# --- Backward-compatible helpers (Phase 1 tests) ---


def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].to_numpy(dtype=float)
    for period, name in ((9, "ema_9"), (21, "ema_21"), (50, "ema_50"), (200, "ema_200")):
        out[name] = _ema_tradingview(c, period)
    return out


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].to_numpy(dtype=float)
    h = out["high"].to_numpy(dtype=float)
    low = out["low"].to_numpy(dtype=float)
    out["rsi_14"] = _rsi_wilder(c, 14)
    out["atr_14"] = _atr_wilder(h, low, c, 14)
    return out