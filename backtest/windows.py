"""Fast windowed slices for backtest (matches live CandleStore windows)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from core.config import ANALYSIS_CANDLES, HTF_CANDLES
from core.indicators import add_all_indicators

OHLCV_COLS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "taker_buy_quote_volume",
)
QVOL_WINDOW_MS = 86_400_000
DAILY_MAX_BARS = 400


def _slice_cols(df: pd.DataFrame) -> list[str]:
    """Keep OHLCV + indicator columns when present (backtest precompute path)."""
    base = [c for c in OHLCV_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in base and c not in ("time",)]
    return base + extra


def precompute_quote_volume_24h(close_ms: np.ndarray, quote_vol: np.ndarray) -> np.ndarray:
    """Rolling 24h quote volume sum at each bar's close_time (O(n) once)."""
    cum = np.concatenate([[0.0], np.cumsum(quote_vol, dtype=np.float64)])
    n = len(close_ms)
    out = np.zeros(n, dtype=np.float64)
    for i in range(n):
        cut = int(close_ms[i]) - QVOL_WINDOW_MS
        j = int(np.searchsorted(close_ms, cut, side="right"))
        out[i] = cum[i + 1] - cum[j]
    return out


@dataclass
class BarWindows:
    """Precomputed index arrays for O(1) window lookup per bar."""

    tf: str
    ltf: pd.DataFrame
    ltf_close_ms: np.ndarray
    qv24: np.ndarray
    htf: dict[str, pd.DataFrame]
    htf_close_ms: dict[str, np.ndarray]
    daily: pd.DataFrame | None
    daily_close_ms: np.ndarray | None
    ltf_cols: list[str] | None = None

    @classmethod
    def from_frames(
        cls,
        tf: str,
        ltf: pd.DataFrame,
        htf_frames: dict[str, pd.DataFrame],
        daily: pd.DataFrame | None,
    ) -> BarWindows:
        ltf = add_all_indicators(ltf.sort_values("time").reset_index(drop=True))
        htf_frames = {
            k: add_all_indicators(frame.sort_values("time").reset_index(drop=True))
            for k, frame in htf_frames.items()
        }
        if daily is not None and not daily.empty:
            daily = daily.sort_values("time").reset_index(drop=True)
        ct = ltf["close_time"].to_numpy(dtype=np.int64)
        qv = ltf["quote_volume"].to_numpy(dtype=np.float64) if "quote_volume" in ltf.columns else np.zeros(len(ltf))
        htf_cm: dict[str, np.ndarray] = {}
        for k, frame in htf_frames.items():
            htf_cm[k] = frame["close_time"].to_numpy(dtype=np.int64)
        dcm = None
        if daily is not None and not daily.empty:
            dcm = daily["close_time"].to_numpy(dtype=np.int64)
        return cls(
            tf=tf,
            ltf=ltf,
            ltf_close_ms=ct,
            qv24=precompute_quote_volume_24h(ct, qv),
            htf=htf_frames,
            htf_close_ms=htf_cm,
            daily=daily,
            daily_close_ms=dcm,
            ltf_cols=None,
        )

    def as_of_ms(self, bar_index: int) -> int:
        return int(self.ltf_close_ms[bar_index])

    def as_of_dt(self, bar_index: int) -> datetime:
        return datetime.fromtimestamp(self.as_of_ms(bar_index) / 1000.0, tz=UTC)

    def ltf_window(self, bar_index: int) -> pd.DataFrame:
        end = bar_index + 1
        start = max(0, end - ANALYSIS_CANDLES)
        cols = self.ltf_cols if self.ltf_cols is not None else _slice_cols(self.ltf)
        return self.ltf.iloc[start:end][cols]

    def htf_windows(self, bar_index: int) -> dict[str, pd.DataFrame]:
        as_ms = self.as_of_ms(bar_index)
        out: dict[str, pd.DataFrame] = {}
        for htf, frame in self.htf.items():
            ct = self.htf_close_ms[htf]
            end = int(np.searchsorted(ct, as_ms, side="right"))
            if end <= 0:
                continue
            start = max(0, end - HTF_CANDLES)
            out[htf] = frame.iloc[start:end][_slice_cols(frame)]
        return out

    def daily_window(self, bar_index: int) -> pd.DataFrame | None:
        if self.daily is None or self.daily_close_ms is None:
            return None
        as_ms = self.as_of_ms(bar_index)
        end = int(np.searchsorted(self.daily_close_ms, as_ms, side="right"))
        if end <= 0:
            return None
        start = max(0, end - DAILY_MAX_BARS)
        return self.daily.iloc[start:end][_slice_cols(self.daily)]

    def quote_volume_24h(self, bar_index: int) -> float:
        return float(self.qv24[bar_index])