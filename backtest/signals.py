"""
Exact signal generation via core.setup_builder.build_setup (two-stage prefilter).
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from backtest.history import ensure_indicators, load_history
from backtest.paths import SIGNALS_DIR, history_parquet
from backtest.prefilter import candidate_mask, mask_fraction
from backtest.windows import BarWindows
from core.config import HIGHER_TIMEFRAMES
from core.exchange_info import tick_size
from core.models import Direction, Setup
from core.setup_builder import build_setup

logger = logging.getLogger(__name__)

SIGNAL_COLUMNS = (
    "symbol",
    "timeframe",
    "bar_index",
    "close_time",
    "as_of",
    "direction",
    "strategy",
    "score",
    "entry",
    "entry_type",
    "stop_loss",
    "tp1",
    "tp2",
    "tp3",
    "setup_id",
)

# Bars per worker chunk (5m histories are long)
CHUNK_SIZE = 1500


def _git_hash() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()[:12]
    except Exception:
        return "nogit"


def signal_cache_path(symbol: str, tf: str) -> Path:
    return SIGNALS_DIR / f"{symbol.upper()}_{tf}.parquet"


def signal_meta_path(symbol: str, tf: str) -> Path:
    return SIGNALS_DIR / f"{symbol.upper()}_{tf}.meta.json"


def cache_key(symbol: str, tf: str) -> str:
    path = history_parquet(symbol, tf)
    stat = path.stat() if path.exists() else None
    payload = {
        "git": _git_hash(),
        "symbol": symbol,
        "tf": tf,
        "rows": int(stat.st_size) if stat else 0,
        "mtime": stat.st_mtime if stat else 0,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def setup_row(symbol: str, tf: str, i: int, close_ms: int, setup: Setup) -> dict:
    return {
        "symbol": symbol,
        "timeframe": tf,
        "bar_index": i,
        "close_time": close_ms,
        "as_of": setup.as_of.isoformat(),
        "direction": setup.direction.value,
        "strategy": setup.strategy,
        "score": setup.score,
        "entry": setup.entry,
        "entry_type": setup.entry_type.value,
        "stop_loss": setup.stop_loss,
        "tp1": setup.tp1,
        "tp2": setup.tp2,
        "tp3": setup.tp3,
        "setup_id": setup.setup_id,
    }


def evaluate_bar(
    symbol: str,
    tf: str,
    windows: BarWindows,
    bar_index: int,
    tick: float,
    *,
    htf_trend_cache: dict | None = None,
) -> dict | None:
    if bar_index < 249:
        return None
    as_of = windows.as_of_dt(bar_index)
    ltf_slice = windows.ltf_window(bar_index)
    if len(ltf_slice) < 250:
        return None
    htf_slices = windows.htf_windows(bar_index)
    daily_slice = windows.daily_window(bar_index)
    qv = windows.quote_volume_24h(bar_index)
    setup = build_setup(
        symbol,
        tf,
        ltf_slice,
        htf_slices,
        daily_slice,
        as_of,
        tick,
        qv,
        htf_trend_cache=htf_trend_cache,
    )
    if setup.direction not in (Direction.LONG, Direction.SHORT):
        return None
    return setup_row(symbol, tf, bar_index, windows.as_of_ms(bar_index), setup)


def _scan_chunk(
    symbol: str,
    tf: str,
    indices: list[int],
    ltf_path: str,
    htf_paths: dict[str, str],
    daily_path: str | None,
    tick: float,
) -> list[dict]:
    ltf = pd.read_parquet(ltf_path)
    htf_frames = {k: pd.read_parquet(p) for k, p in htf_paths.items()}
    daily = pd.read_parquet(daily_path) if daily_path else None
    windows = BarWindows.from_frames(tf, ltf, htf_frames, daily)
    htf_cache: dict = {}
    rows: list[dict] = []
    for i in indices:
        row = evaluate_bar(symbol, tf, windows, i, tick, htf_trend_cache=htf_cache)
        if row:
            rows.append(row)
    return rows


def generate_signals(
    symbol: str,
    tf: str,
    *,
    use_cache: bool = True,
    progress: bool = True,
    workers: int | None = None,
) -> pd.DataFrame:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = signal_meta_path(symbol, tf)
    out_path = signal_cache_path(symbol, tf)
    key = cache_key(symbol, tf)
    if use_cache and meta_path.exists() and out_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("cache_key") == key:
            return pd.read_parquet(out_path)

    ltf_raw = load_history(symbol, tf)
    ltf_ind = ensure_indicators(ltf_raw)
    mask = candidate_mask(ltf_ind)
    frac = mask_fraction(mask)
    logger.info("prefilter %s %s: %.1f%% of bars (%d/%d)", symbol, tf, frac * 100, mask.sum(), len(mask))

    indices = np.nonzero(mask)[0].tolist()
    htf_frames: dict[str, pd.DataFrame] = {}
    htf_paths: dict[str, str] = {}
    for htf in HIGHER_TIMEFRAMES.get(tf, ()):
        htf_frames[htf] = load_history(symbol, htf)
        htf_paths[htf] = str(history_parquet(symbol, htf))
    daily_df = load_history(symbol, "1d") if history_parquet(symbol, "1d").exists() else None
    daily_path = str(history_parquet(symbol, "1d")) if daily_df is not None else None
    tick = float(tick_size(symbol))

    t0 = time.perf_counter()
    rows: list[dict] = []
    w = workers if workers is not None else max(1, multiprocessing.cpu_count() - 1)

    if w <= 1 or len(indices) < CHUNK_SIZE:
        windows = BarWindows.from_frames(tf, ltf_raw, htf_frames, daily_df)
        htf_cache: dict = {}
        it = tqdm(indices, desc=f"{symbol} {tf}", unit="bar", disable=not progress)
        for i in it:
            row = evaluate_bar(symbol, tf, windows, i, tick, htf_trend_cache=htf_cache)
            if row:
                rows.append(row)
    else:
        chunks = [indices[i : i + CHUNK_SIZE] for i in range(0, len(indices), CHUNK_SIZE)]
        ltf_path = str(history_parquet(symbol, tf))
        with ProcessPoolExecutor(max_workers=w) as pool:
            futs = {
                pool.submit(_scan_chunk, symbol, tf, ch, ltf_path, htf_paths, daily_path, tick): len(ch)
                for ch in chunks
            }
            with tqdm(total=len(indices), desc=f"{symbol} {tf}", unit="bar", disable=not progress) as pbar:
                for fut in as_completed(futs):
                    rows.extend(fut.result())
                    pbar.update(futs[fut])

    elapsed = time.perf_counter() - t0
    bps = len(indices) / elapsed if elapsed > 0 else 0.0
    logger.info(
        "signals %s %s: %d setups from %d bars in %.1fs (%.1f bars/s)",
        symbol,
        tf,
        len(rows),
        len(indices),
        elapsed,
        bps,
    )

    df = pd.DataFrame(rows, columns=SIGNAL_COLUMNS) if rows else pd.DataFrame(columns=SIGNAL_COLUMNS)
    df.to_parquet(out_path, index=False)
    meta_path.write_text(
        json.dumps({"cache_key": key, "rows": len(df), "mask_fraction": frac, "bars_per_sec": bps}, indent=2),
        encoding="utf-8",
    )
    return df


def generate_all(
    symbols: list[str],
    timeframes: list[str],
    *,
    workers: int | None = None,
) -> dict[tuple[str, str], pd.DataFrame]:
    tasks = [(s, tf) for s in symbols for tf in timeframes]
    out: dict[tuple[str, str], pd.DataFrame] = {}
    pool_workers = max(1, min(len(tasks), (workers or max(1, multiprocessing.cpu_count() - 1))))
    with ProcessPoolExecutor(max_workers=pool_workers) as pool:
        futs = {pool.submit(generate_signals, s, tf, progress=False, workers=1): (s, tf) for s, tf in tasks}
        for fut in as_completed(futs):
            s, tf = futs[fut]
            out[(s, tf)] = fut.result()
    return out