"""
Typed dataclasses for analysis results (pure setup engine output).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class EntryType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class SetupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class TrendBias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Swing:
    """Confirmed pivot (no look-ahead: confirmed_time <= as_of)."""

    pivot_time: datetime
    confirmed_time: datetime
    price: float
    kind: str  # "high" | "low"


@dataclass(frozen=True)
class Zone:
    price_low: float
    price_high: float
    mid: float
    touches: int
    last_touch_time: datetime
    strength: float
    role: str  # "support" | "resistance" (position vs reference price)
    origin: str = "high"  # pivot source: high | low | vwap
    flipped: bool = False  # True when role vs pivot kind disagrees (S/R flip)


@dataclass(frozen=True)
class TrendResult:
    bias: TrendBias
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreBreakdown:
    """Transparent score components (sum caps at 100 before penalties)."""

    htf: float = 0.0
    level_quality: float = 0.0
    momentum: float = 0.0
    volume: float = 0.0
    candle_confirmation: float = 0.0
    net_rr: float = 0.0
    volatility: float = 0.0
    penalties: float = 0.0

    @property
    def total(self) -> float:
        raw = (
            self.htf
            + self.level_quality
            + self.momentum
            + self.volume
            + self.candle_confirmation
            + self.net_rr
            + self.volatility
            - self.penalties
        )
        return max(0.0, min(100.0, raw))


@dataclass(frozen=True)
class Setup:
    symbol: str
    timeframe: str
    direction: Direction
    strategy: str
    entry: float
    entry_type: EntryType
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    sl_pct: float
    tp_pcts: tuple[float, float, float]
    gross_rr: tuple[float, float, float]
    net_rr: tuple[float, float, float]
    score: float
    breakdown: ScoreBreakdown
    reasons: tuple[str, ...]
    htf_trends: dict[str, TrendResult]
    levels_used: tuple[str, ...]
    signal_candle_time: datetime
    as_of: datetime
    setup_id: str
    status: SetupStatus = SetupStatus.ACTIVE
    expires_at: datetime | None = None
    rejected_candidate: Setup | None = None

    @staticmethod
    def make_setup_id(
        symbol: str,
        timeframe: str,
        direction: Direction,
        strategy: str,
        signal_candle_time: datetime,
    ) -> str:
        """Short SHA-256 id for de-duplication."""
        payload = f"{symbol}|{timeframe}|{direction.value}|{strategy}|{signal_candle_time.isoformat()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def no_trade(
    symbol: str,
    timeframe: str,
    reasons: tuple[str, ...],
    as_of: datetime,
    rejected: Setup | None = None,
) -> Setup:
    """Factory for NO_TRADE setups."""
    stub = datetime.fromtimestamp(0)
    return Setup(
        symbol=symbol,
        timeframe=timeframe,
        direction=Direction.NO_TRADE,
        strategy="none",
        entry=0.0,
        entry_type=EntryType.MARKET,
        stop_loss=0.0,
        tp1=0.0,
        tp2=0.0,
        tp3=0.0,
        sl_pct=0.0,
        tp_pcts=(0.0, 0.0, 0.0),
        gross_rr=(0.0, 0.0, 0.0),
        net_rr=(0.0, 0.0, 0.0),
        score=0.0,
        breakdown=ScoreBreakdown(),
        reasons=reasons,
        htf_trends={},
        levels_used=(),
        signal_candle_time=stub,
        as_of=as_of,
        setup_id=Setup.make_setup_id(symbol, timeframe, Direction.NO_TRADE, "none", stub),
        rejected_candidate=rejected,
    )