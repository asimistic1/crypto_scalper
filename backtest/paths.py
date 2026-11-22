"""Filesystem layout for backtest artifacts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = REPO_ROOT / "data" / "history"
FUNDING_DIR = REPO_ROOT / "data" / "history" / "_funding"
SIGNALS_DIR = REPO_ROOT / "data" / "backtest" / "signals"
RUNS_DIR = REPO_ROOT / "data" / "backtest" / "runs"
DATASET_PATH = REPO_ROOT / "data" / "backtest" / "dataset.parquet"


def history_parquet(symbol: str, interval: str) -> Path:
    return HISTORY_DIR / symbol.upper() / f"{interval}.parquet"


def funding_parquet(symbol: str) -> Path:
    return FUNDING_DIR / f"{symbol.upper()}.parquet"


def symbol_aux_parquet(symbol: str, stem: str) -> Path:
    """Research/auxiliary series under data/history/{SYMBOL}/{stem}.parquet."""
    return HISTORY_DIR / symbol.upper() / f"{stem}.parquet"


def download_gaps_path(symbol: str) -> Path:
    return HISTORY_DIR / symbol.upper() / "download_gaps.json"