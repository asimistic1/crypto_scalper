"""
Central thresholds for the trade setup engine (Phase 2).
All analysis code reads from here — no magic numbers elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# --- Timeframes ---
TIMEFRAMES_ALLOWED: tuple[str, ...] = ("5m", "15m", "1h")

HIGHER_TIMEFRAMES: Mapping[str, tuple[str, ...]] = {
    "5m": ("15m", "1h"),
    "15m": ("1h", "4h"),
    "1h": ("4h", "1d"),
}

ANALYSIS_CANDLES = 1000
HTF_CANDLES = 300

# --- Fees & slippage (per side; round-trip = 2× taker + 2× slippage) ---
TAKER_FEE = 0.0005
MAKER_FEE = 0.0002
SLIPPAGE = 0.0002

# --- Structure / zones ---
SWING_LEFT = 5
SWING_RIGHT = 5
SR_ZONE_TOLERANCE_ATR = 0.5
SR_MAX_ZONES_EACH_SIDE = 3
ZONE_RECENCY_HALF_LIFE_CANDLES = 200

# --- Stop / entry ---
SL_BUFFER_ATR = 0.2
SL_MIN_ATR = 0.5
SL_MAX_ATR = 2.5
LIMIT_ENTRY_MAX_DISTANCE_ATR = 0.3

# --- R:R & scoring gates ---
MIN_NET_RR_TP1 = 1.0
MIN_SL_VS_COSTS = 3.0
MIN_SETUP_SCORE = 55
FALLBACK_TP_R: tuple[float, float, float] = (1.0, 2.0, 3.0)

# --- Liquidity & data quality ---
MIN_24H_QUOTE_VOLUME_USDT = 50_000_000
SETUP_EXPIRY_CANDLES = 3
STALE_DATA_MAX_PERIODS = 2

# ATR% of price = 100 * ATR / close — suitability band per LTF
ATR_PCT_BOUNDS: Mapping[str, tuple[float, float]] = {
    "5m": (0.05, 2.5),
    "15m": (0.08, 4.0),
    "1h": (0.15, 8.0),
}


@dataclass(frozen=True)
class ScoreWeights:
    """Setup quality score components (not win probability)."""

    htf: int = 25
    level_quality: int = 20
    momentum: int = 15
    volume: int = 15
    candle_confirmation: int = 10
    net_rr: int = 10
    volatility: int = 5
    opposing_zone_penalty: int = 15


SCORE_WEIGHTS = ScoreWeights()

# Binance API weight budget (self-imposed, below exchange limits)
WEIGHT_BUDGET_PER_MINUTE = 1_000
WEIGHT_BUDGET_SOFT_LIMIT = 800

EXCHANGE_INFO_CACHE_HOURS = 6
SERVER_TIME_CACHE_SECONDS = 600
CANDLE_STORE_EVICT_MINUTES = 30