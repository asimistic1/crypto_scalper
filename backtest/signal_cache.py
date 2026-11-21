"""SHA-256 cache key for signal parquet (code + config + data file only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import core.config as core_cfg
from backtest.paths import history_parquet

ROOT = Path(__file__).resolve().parents[1]

# Source files that affect generated signals (not metrics / reporting).
_SIGNAL_SOURCE_GLOBS = (
    "core/**/*.py",
    "backtest/signals.py",
    "backtest/prefilter.py",
    "backtest/windows.py",
)


def _iter_signal_sources() -> list[Path]:
    files: set[Path] = set()
    for pattern in _SIGNAL_SOURCE_GLOBS:
        files.update(ROOT.glob(pattern))
    return sorted(files)


def _core_config_snapshot() -> dict:
    """Values from core.config that change setup selection."""
    w = core_cfg.SCORE_WEIGHTS
    return {
        "TIMEFRAMES_ALLOWED": core_cfg.TIMEFRAMES_ALLOWED,
        "HIGHER_TIMEFRAMES": {k: v for k, v in core_cfg.HIGHER_TIMEFRAMES.items()},
        "ANALYSIS_CANDLES": core_cfg.ANALYSIS_CANDLES,
        "HTF_CANDLES": core_cfg.HTF_CANDLES,
        "SWING_LEFT": core_cfg.SWING_LEFT,
        "SWING_RIGHT": core_cfg.SWING_RIGHT,
        "SR_ZONE_TOLERANCE_ATR": core_cfg.SR_ZONE_TOLERANCE_ATR,
        "SR_MAX_ZONES_EACH_SIDE": core_cfg.SR_MAX_ZONES_EACH_SIDE,
        "ZONE_RECENCY_HALF_LIFE_CANDLES": core_cfg.ZONE_RECENCY_HALF_LIFE_CANDLES,
        "SL_BUFFER_ATR": core_cfg.SL_BUFFER_ATR,
        "SL_MIN_ATR": core_cfg.SL_MIN_ATR,
        "SL_MAX_ATR": core_cfg.SL_MAX_ATR,
        "LIMIT_ENTRY_MAX_DISTANCE_ATR": core_cfg.LIMIT_ENTRY_MAX_DISTANCE_ATR,
        "MIN_NET_RR_TP1": core_cfg.MIN_NET_RR_TP1,
        "MIN_SL_VS_COSTS": core_cfg.MIN_SL_VS_COSTS,
        "MIN_SETUP_SCORE": core_cfg.MIN_SETUP_SCORE,
        "FALLBACK_TP_R": core_cfg.FALLBACK_TP_R,
        "MIN_24H_QUOTE_VOLUME_USDT": core_cfg.MIN_24H_QUOTE_VOLUME_USDT,
        "SETUP_EXPIRY_CANDLES": core_cfg.SETUP_EXPIRY_CANDLES,
        "STALE_DATA_MAX_PERIODS": core_cfg.STALE_DATA_MAX_PERIODS,
        "ATR_PCT_BOUNDS": {k: v for k, v in core_cfg.ATR_PCT_BOUNDS.items()},
        "SCORE_WEIGHTS": {
            "htf": w.htf,
            "level_quality": w.level_quality,
            "momentum": w.momentum,
            "volume": w.volume,
            "candle_confirmation": w.candle_confirmation,
            "net_rr": w.net_rr,
            "volatility": w.volatility,
            "opposing_zone_penalty": w.opposing_zone_penalty,
        },
    }


def cache_key(symbol: str, tf: str) -> str:
    path = history_parquet(symbol, tf)
    stat = path.stat() if path.exists() else None
    file_hashes: dict[str, str] = {}
    for fp in _iter_signal_sources():
        rel = str(fp.relative_to(ROOT)).replace("\\", "/")
        h = hashlib.sha256(fp.read_bytes()).hexdigest()
        file_hashes[rel] = h
    payload = {
        "symbol": symbol.upper(),
        "tf": tf,
        "history_bytes": int(stat.st_size) if stat else 0,
        "history_mtime_ns": int(stat.st_mtime_ns) if stat else 0,
        "core_config": _core_config_snapshot(),
        "sources": file_hashes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]