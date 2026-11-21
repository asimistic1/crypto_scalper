"""
Market structure: confirmed swings, S/R zones, and auxiliary levels.

Pure analysis — no network calls. Respects as_of to avoid look-ahead.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from core.config import (
    SR_MAX_ZONES_EACH_SIDE,
    SR_ZONE_TOLERANCE_ATR,
    SWING_LEFT,
    SWING_RIGHT,
    ZONE_RECENCY_HALF_LIFE_CANDLES,
)
from core.models import Swing, Zone


def _time_ms_array(df: pd.DataFrame) -> np.ndarray:
    """Bar open times as int64 epoch ns (UTC) — same ordering as pd.to_datetime <= ts."""
    t = pd.to_datetime(df["time"], utc=True)
    return t.to_numpy(dtype="datetime64[ns]").view(np.int64)


def _close_time_ms_array(df: pd.DataFrame) -> np.ndarray:
    if "close_time" in df.columns:
        return df["close_time"].to_numpy(dtype=np.int64)
    return _time_ms_array(df)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _row_time(series_time: pd.Series, idx: int) -> datetime:
    ts = series_time.iloc[idx]
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return pd.Timestamp(ts).to_pydatetime()


def _row_confirmed_time(df: pd.DataFrame, idx: int) -> datetime:
    if "close_time" in df.columns:
        cts = df["close_time"].iloc[idx]
        if pd.notna(cts):
            if isinstance(cts, (int, np.integer)):
                return _ms_to_dt(int(cts))
            return pd.Timestamp(cts).to_pydatetime()
    return _row_time(df["time"], idx)


def find_swings(
    df: pd.DataFrame,
    left: int = SWING_LEFT,
    right: int = SWING_RIGHT,
) -> list[Swing]:
    """
  Vectorized pivot detection. A pivot at index i is only known after bar i+right closes
  (confirmed_time on that bar).
    """
    required = {"time", "high", "low"}
    if not required.issubset(df.columns):
        raise ValueError(f"find_swings needs columns {required}")

    n = len(df)
    if n < left + right + 1:
        return []

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    w = left + right + 1
    win_h = np.lib.stride_tricks.sliding_window_view(high, w)
    win_l = np.lib.stride_tricks.sliding_window_view(low, w)

    # Window k starts at pivot_index - left → pivot at pivot_index = k + left
    pivot_indices = np.arange(left, n - right)
    win_rows = pivot_indices - left
    center = left

    is_high = win_h[win_rows, center] == win_h[win_rows].max(axis=1)
    is_low = win_l[win_rows, center] == win_l[win_rows].min(axis=1)

    time_ms = _time_ms_array(df)
    close_ms = _close_time_ms_array(df)
    swings: list[Swing] = []
    for j, pi in enumerate(pivot_indices):
        conf_idx = pi + right
        p_dt = pd.Timestamp(int(time_ms[pi]), unit="ns", tz="UTC").to_pydatetime()
        c_dt = _ms_to_dt(int(close_ms[conf_idx]))
        if is_high[j]:
            swings.append(
                Swing(
                    pivot_time=p_dt,
                    confirmed_time=c_dt,
                    price=float(high[pi]),
                    kind="high",
                )
            )
        if is_low[j]:
            swings.append(
                Swing(
                    pivot_time=p_dt,
                    confirmed_time=c_dt,
                    price=float(low[pi]),
                    kind="low",
                )
            )

    swings.sort(key=lambda s: (s.pivot_time, s.kind))
    return swings


def swings_confirmed_as_of(swings: Sequence[Swing], as_of: datetime) -> list[Swing]:
    """Keep only swings that are fully confirmed at analysis time."""
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    return [s for s in swings if _aware(s.confirmed_time) <= as_of]


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _decay_weight(candles_ago: float, half_life: float) -> float:
    if half_life <= 0:
        return 1.0
    return 0.5 ** (candles_ago / half_life)


def _bar_index_at_or_before(df: pd.DataFrame, ts: datetime) -> int:
    bar_ns = _time_ms_array(df)
    if len(bar_ns) == 0:
        return 0
    pt = pd.Timestamp(_aware(ts))
    if pt.tzinfo is None:
        pt = pt.tz_localize("UTC")
    else:
        pt = pt.tz_convert("UTC")
    ts_ns = int(pt.value)
    idx = int(np.searchsorted(bar_ns, ts_ns, side="right")) - 1
    return max(0, idx)


def build_zones(
    swings: Sequence[Swing],
    atr: float,
    *,
    reference_price: float,
    df: pd.DataFrame,
    as_of: datetime,
    tolerance_atr: float = SR_ZONE_TOLERANCE_ATR,
    half_life: float = ZONE_RECENCY_HALF_LIFE_CANDLES,
) -> list[Zone]:
    """
    Cluster pivots into zones. Role vs reference_price: above = resistance, below = support.
    Recency uses bar indices (as_of index − pivot index).
    """
    if atr <= 0 or not swings or df.empty:
        return []

    as_of = _aware(as_of)
    as_of_idx = _bar_index_at_or_before(df, as_of)
    time_ms = _time_ms_array(df)
    tol = tolerance_atr * atr
    by_kind: dict[str, list[Swing]] = {"high": [], "low": []}
    for s in swings:
        by_kind[s.kind].append(s)

    zones: list[Zone] = []
    for kind, pivot_role in (("low", "support"), ("high", "resistance")):
        pivots = sorted(by_kind[kind], key=lambda s: s.price)
        if not pivots:
            continue

        clusters: list[list[Swing]] = []
        cur: list[Swing] = [pivots[0]]
        for p in pivots[1:]:
            cluster_mid = float(np.mean([x.price for x in cur]))
            if abs(p.price - cluster_mid) <= tol:
                cur.append(p)
            else:
                clusters.append(cur)
                cur = [p]
        clusters.append(cur)

        for cluster in clusters:
            prices = [c.price for c in cluster]
            low_p, high_p = min(prices), max(prices)
            mid = float(np.mean(prices))
            touches = len(cluster)
            last_touch = max(cluster, key=lambda s: s.pivot_time).pivot_time

            weighted = 0.0
            for s in cluster:
                p_ns = int(pd.Timestamp(_aware(s.pivot_time)).tz_convert("UTC").value)
                pivot_idx = int(np.searchsorted(time_ms, p_ns, side="right")) - 1
                pivot_idx = max(0, pivot_idx)
                candles_ago = max(0, as_of_idx - pivot_idx)
                weighted += _decay_weight(float(candles_ago), half_life)

            role = "resistance" if mid > reference_price else "support"
            flipped = role != pivot_role

            strength = weighted + (0.35 if flipped else 0.0)
            zones.append(
                Zone(
                    price_low=low_p,
                    price_high=high_p,
                    mid=mid,
                    touches=touches,
                    last_touch_time=_aware(last_touch),
                    strength=float(strength),
                    role=role,
                    origin=kind,
                    flipped=flipped,
                )
            )

    zones.sort(key=lambda z: z.mid)
    return zones


def previous_utc_day_hl(df_1d: pd.DataFrame, as_of: datetime) -> tuple[float | None, float | None]:
    """High/low of the last fully closed UTC daily candle at as_of."""
    if df_1d.empty or "time" not in df_1d.columns:
        return None, None
    as_of = _aware(as_of)
    work = df_1d.copy()
    if "close_time" in work.columns:
        ct = work["close_time"]
        if pd.api.types.is_integer_dtype(ct):
            mask = pd.to_datetime(ct, unit="ms", utc=True) <= as_of
        else:
            mask = pd.to_datetime(ct, utc=True) <= as_of
        work = work.loc[mask]
    else:
        work = work.loc[pd.to_datetime(work["time"], utc=True) <= as_of]
    if work.empty:
        return None, None
    row = work.iloc[-1]
    return float(row["high"]), float(row["low"])


def current_daily_vwap(df: pd.DataFrame, as_of: datetime) -> float | None:
    """VWAP for the UTC day containing as_of, using only bars with time <= as_of."""
    if "vwap_daily" not in df.columns or df.empty:
        return None
    as_of = _aware(as_of)
    times = pd.to_datetime(df["time"], utc=True)
    mask = times <= as_of
    if not mask.any():
        return None
    day = as_of.date()
    day_mask = mask & (times.dt.date == day)
    if not day_mask.any():
        return None
    v = df.loc[day_mask, "vwap_daily"].iloc[-1]
    return float(v) if pd.notna(v) else None


def extra_levels(
    df_ltf: pd.DataFrame,
    df_1d: pd.DataFrame | None,
    as_of: datetime,
    atr: float,
) -> list[Zone]:
    """Synthetic zones for prior day H/L and current session VWAP."""
    zones: list[Zone] = []
    band = max(atr * 0.05, 1e-8)

    if df_1d is not None:
        d_hi, d_lo = previous_utc_day_hl(df_1d, as_of)
        if d_hi is not None:
            zones.append(
                Zone(
                    price_low=d_hi - band,
                    price_high=d_hi + band,
                    mid=d_hi,
                    touches=1,
                    last_touch_time=as_of,
                    strength=1.2,
                    role="resistance",
                    origin="high",
                )
            )
        if d_lo is not None:
            zones.append(
                Zone(
                    price_low=d_lo - band,
                    price_high=d_lo + band,
                    mid=d_lo,
                    touches=1,
                    last_touch_time=as_of,
                    strength=1.2,
                    role="support",
                    origin="low",
                )
            )

    vwap = current_daily_vwap(df_ltf, as_of)
    if vwap is not None:
        zones.append(
            Zone(
                price_low=vwap - band,
                price_high=vwap + band,
                mid=vwap,
                touches=1,
                last_touch_time=as_of,
                strength=1.0,
                role="support",
                origin="vwap",
            )
        )
    return zones


def nearest_zones(
    zones: Sequence[Zone],
    price: float,
    n: int = SR_MAX_ZONES_EACH_SIDE,
) -> tuple[list[Zone], list[Zone]]:
    """Up to n support zones below price and resistance zones above."""
    below = [z for z in zones if z.mid <= price]
    above = [z for z in zones if z.mid > price]
    below.sort(key=lambda z: price - z.mid)
    above.sort(key=lambda z: z.mid - price)
    return below[:n], above[:n]


def structure_for_symbol(
    df: pd.DataFrame,
    as_of: datetime,
    atr: float,
    df_1d: pd.DataFrame | None = None,
) -> tuple[list[Swing], list[Zone]]:
    """Convenience: swings confirmed at as_of + zones (+ extras)."""
    all_swings = find_swings(df)
    swings = swings_confirmed_as_of(all_swings, as_of)
    if not swings:
        zones = extra_levels(df, df_1d, as_of, atr) if df_1d is not None or "vwap_daily" in df.columns else []
        return [], zones

    close = float(df.iloc[_last_index_at_or_before(df, as_of) or -1]["close"])
    zones = build_zones(
        swings,
        atr,
        reference_price=close,
        df=df,
        as_of=as_of,
    )
    zones = sorted(zones + extra_levels(df, df_1d, as_of, atr), key=lambda z: z.mid)
    return swings, zones


def _last_index_at_or_before(df: pd.DataFrame, as_of: datetime) -> int | None:
    as_of = _aware(as_of)
    if "close_time" in df.columns:
        ct = df["close_time"]
        if pd.api.types.is_integer_dtype(ct):
            times = pd.to_datetime(ct, unit="ms", utc=True)
        else:
            times = pd.to_datetime(ct, utc=True)
    else:
        times = pd.to_datetime(df["time"], utc=True)
    mask = times <= as_of
    if not mask.any():
        return None
    return int(mask.to_numpy().nonzero()[0][-1])