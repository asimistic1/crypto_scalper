"""
Exact signal generation via core.setup_builder.build_setup (two-stage prefilter).

Cache: data/backtest/signals/{SYMBOL}_{tf}.parquet
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from backtest.history import (
    as_of_from_close_ms,
    ensure_indicators,
    load_history,
    quote_volume_24h_at,
    slice_ltf_window,
)
from backtest.paths import SIGNALS_DIR, history_parquet
from backtest.prefilter import candidate_mask
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
    ltf_ind: pd.DataFrame,
    htf_cache: dict[str, pd.DataFrame],
    daily_df: pd.DataFrame | None,
    i: int,
    tick: float,
) -> dict | None:
    row = ltf_ind.iloc[i]
    close_ms = int(row["close_time"])
    as_of = as_of_from_close_ms(close_ms)
    closed = slice_ltf_window(ltf_ind, as_of)
    if len(closed) < 250:
        return None
    htf_full = {htf: htf_cache[htf] for htf in HIGHER_TIMEFRAMES.get(tf, ())}
    daily = daily_df
    qv = quote_volume_24h_at(ltf_ind, as_of)
    setup = build_setup(symbol, tf, ltf_ind, htf_full, daily, as_of, tick, qv)
    if setup.direction not in (Direction.LONG, Direction.SHORT):
        return None
    return setup_row(symbol, tf, i, close_ms, setup)


def generate_signals(
    symbol: str,
    tf: str,
    *,
    use_cache: bool = True,
    progress: bool = True,
) -> pd.DataFrame:
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = signal_meta_path(symbol, tf)
    out_path = signal_cache_path(symbol, tf)
    key = cache_key(symbol, tf)
    if use_cache and meta_path.exists() and out_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("cache_key") == key:
            return pd.read_parquet(out_path)

    ltf = load_history(symbol, tf)
    ltf = ensure_indicators(ltf)
    mask = candidate_mask(ltf)
    indices = [i for i in range(len(ltf)) if mask[i]]
    htf_cache: dict[str, pd.DataFrame] = {tf: ltf}
    for htf in HIGHER_TIMEFRAMES.get(tf, ()):
        htf_cache[htf] = ensure_indicators(load_history(symbol, htf))
    daily_df = ensure_indicators(load_history(symbol, "1d")) if history_parquet(symbol, "1d").exists() else None
    tick = float(tick_size(symbol))

    rows: list[dict] = []
    it = indices
    if progress:
        it = tqdm(indices, desc=f"{symbol} {tf}", unit="bar")
    for i in it:
        row = evaluate_bar(symbol, tf, ltf, htf_cache, daily_df, i, tick)
        if row:
            rows.append(row)
    df = pd.DataFrame(rows, columns=SIGNAL_COLUMNS) if rows else pd.DataFrame(columns=SIGNAL_COLUMNS)
    df.to_parquet(out_path, index=False)
    meta_path.write_text(json.dumps({"cache_key": key, "rows": len(df)}, indent=2), encoding="utf-8")
    return df


def generate_all(
    symbols: list[str],
    timeframes: list[str],
    *,
    workers: int = 3,
) -> dict[tuple[str, str], pd.DataFrame]:
    tasks = [(s, tf) for s in symbols for tf in timeframes]
    out: dict[tuple[str, str], pd.DataFrame] = {}
    if workers <= 1:
        for s, tf in tasks:
            out[(s, tf)] = generate_signals(s, tf)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(generate_signals, s, tf, progress=False): (s, tf) for s, tf in tasks}
        for fut in as_completed(futs):
            s, tf = futs[fut]
            out[(s, tf)] = fut.result()
    return out