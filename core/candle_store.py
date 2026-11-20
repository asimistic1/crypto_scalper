"""
Incremental closed-candle cache (numpy/pandas, process-wide).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config import (
    ANALYSIS_CANDLES,
    HTF_CANDLES,
    STALE_DATA_MAX_PERIODS,
    TIMEFRAMES_ALLOWED,
)
from core.exchange_info import binance_server_time_ms
from core.http_client import fapi_get
from core.rate_limit import BinanceCooldownActive, is_in_cooldown, last_http_code, seconds_remaining
from core.security import validate_symbol_rest, validate_timeframe

_TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

_store_lock = threading.Lock()
_entries: dict[tuple[str, str], _Entry] = {}


@dataclass
class CandleFetchResult:
    df: pd.DataFrame
    stale: bool
    from_cache: bool


@dataclass
class _Entry:
    df: pd.DataFrame
    last_access: float
    lock: threading.Lock


def _max_bars(tf: str) -> int:
    return HTF_CANDLES if tf not in TIMEFRAMES_ALLOWED else ANALYSIS_CANDLES


def _period_ms(tf: str) -> int:
    if tf not in _TF_MS:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return _TF_MS[tf]


def _klines_to_df(raw: list) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "close_time"])
    arr = np.asarray(raw, dtype=object)
    open_times = arr[:, 0].astype(np.int64)
    closes = arr[:, 4].astype(np.float64)
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(open_times, unit="ms", utc=True),
            "open": arr[:, 1].astype(np.float64),
            "high": arr[:, 2].astype(np.float64),
            "low": arr[:, 3].astype(np.float64),
            "close": closes,
            "volume": arr[:, 5].astype(np.float64),
            "close_time": arr[:, 6].astype(np.int64),
        }
    )
    return df


def _drop_unclosed(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Keep only candles whose close_time is before Binance server time."""
    if df.empty:
        return df
    now = binance_server_time_ms()
    closed = df[df["close_time"] <= now].copy()
    return closed


def _integrity_ok(df: pd.DataFrame, tf: str) -> bool:
    if df.empty:
        return True
    if df["time"].duplicated().any():
        return False
    if not df["time"].is_monotonic_increasing:
        return False
    period = pd.Timedelta(milliseconds=_period_ms(tf))
    diffs = df["time"].diff().dropna()
    if not (diffs == period).all():
        return False
    if (df["high"] < df["low"]).any():
        return False
    return True


def _fetch_klines(symbol: str, tf: str, limit: int) -> pd.DataFrame:
    if is_in_cooldown():
        raise BinanceCooldownActive(seconds_remaining(), last_http_code())
    resp = fapi_get(
        "/fapi/v1/klines",
        {"symbol": symbol, "interval": tf, "limit": limit},
    )
    df = _klines_to_df(resp.json())
    return _drop_unclosed(df, tf)


def _is_stale(df: pd.DataFrame, tf: str) -> bool:
    if df.empty:
        return True
    last_close = int(df["close_time"].iloc[-1])
    now = binance_server_time_ms()
    return (now - last_close) > STALE_DATA_MAX_PERIODS * _period_ms(tf)


def get_closed_candles(symbol: str, timeframe: str, *, full: bool = False) -> CandleFetchResult:
    ok, sym = validate_symbol_rest(symbol)
    if not ok:
        raise ValueError(sym)
    tf = timeframe
    if tf in TIMEFRAMES_ALLOWED:
        ok_tf, tf_msg = validate_timeframe(tf)
        if not ok_tf:
            raise ValueError(tf_msg)

    key = (sym, tf)
    max_bars = _max_bars(tf) if tf in TIMEFRAMES_ALLOWED else HTF_CANDLES

    with _store_lock:
        entry = _entries.get(key)
        if entry is None:
            entry = _Entry(df=pd.DataFrame(), last_access=time.time(), lock=threading.Lock())
            _entries[key] = entry

    with entry.lock:
        entry.last_access = time.time()
        from_cache = not entry.df.empty and not full

        if entry.df.empty or full:
            entry.df = _fetch_klines(sym, tf, min(max_bars, 1000))
            if not _integrity_ok(entry.df, tf):
                entry.df = _fetch_klines(sym, tf, min(max_bars, 1000))
        else:
            tail = _fetch_klines(sym, tf, 3)
            if not tail.empty:
                merged = pd.concat([entry.df, tail], ignore_index=True)
                merged = merged.drop_duplicates(subset=["time"], keep="last")
                merged = merged.sort_values("time").tail(max_bars).reset_index(drop=True)
                if not _integrity_ok(merged, tf):
                    entry.df = _fetch_klines(sym, tf, min(max_bars, 1000))
                else:
                    entry.df = merged

        stale = _is_stale(entry.df, tf)
        return CandleFetchResult(df=entry.df.copy(), stale=stale, from_cache=from_cache)


def get_many(symbol: str, timeframes: tuple[str, ...]) -> dict[str, CandleFetchResult]:
    out: dict[str, CandleFetchResult] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(get_closed_candles, symbol, tf): tf for tf in timeframes}
        for fut in as_completed(futs):
            tf = futs[fut]
            out[tf] = fut.result()
    return out


def evict_idle(max_idle_seconds: float = 30 * 60) -> None:
    now = time.time()
    with _store_lock:
        dead = [k for k, v in _entries.items() if now - v.last_access > max_idle_seconds]
        for k in dead:
            del _entries[k]


def reset_for_tests() -> None:
    with _store_lock:
        _entries.clear()