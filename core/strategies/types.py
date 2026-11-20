"""Shared types for strategy detectors (pure analysis)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.models import Direction, TrendResult, Zone


@dataclass(frozen=True)
class StrategyContext:
    """Everything a strategy needs — all series are closed through as_of."""

    symbol: str
    timeframe: str
    df: pd.DataFrame
    htf_trends: dict[str, TrendResult]
    zones: tuple[Zone, ...]
    as_of: datetime
    tick_size: float


@dataclass(frozen=True)
class StrategyCandidate:
    """Direction + context for setup_builder (Step 6 fills prices and score)."""

    direction: Direction
    strategy: str
    signal_candle_time: datetime
    reasons: tuple[str, ...]
    pick_score: float  # tie-break when two strategies agree on direction
    confirmation_candle: bool = False
    reacted_zone: Zone | None = None
    reaction_source: str = "none"  # zone | ema21 | vwap