"""Backtest configuration (Phase 3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class BacktestConfig:
    taker_fee: float = 0.0005
    maker_fee: float = 0.0002
    slippage: float = 0.0002
    fee_model: str = "conservative"  # conservative | standard
    apply_funding: bool = True
    exit_models: tuple[str, ...] = ("tp1_full", "partial_be")
    max_hold_bars: dict[str, int] = field(
        default_factory=lambda: {"5m": 48, "15m": 32, "1h": 24}
    )
    one_position_per_symbol: bool = True
    risk_per_trade_pct: float = 0.5
    compounding: bool = False
    intrabar_resolution: str = "conservative"  # conservative | 1m
    in_sample_fraction: float = 0.60
    random_seed: int = 42
    min_setup_score: float = 55.0
    ltf_timeframes: tuple[str, ...] = ("5m", "15m", "1h")
    # Low-fee venue (e.g. MEXC) — update when fee schedule is confirmed
    low_fee_taker: float = 0.0002
    low_fee_maker: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)