"""
Run all strategy detectors and resolve conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.models import Direction

from . import breakout_retest, trend_pullback
from .types import StrategyCandidate, StrategyContext


@dataclass(frozen=True)
class StrategyRunResult:
    """Winner, none, or explicit conflict."""

    candidate: StrategyCandidate | None
    conflict: bool = False
    conflict_reason: str | None = None


def run_strategies(ctx: StrategyContext) -> StrategyRunResult:
    found: list[StrategyCandidate] = []
    for fn in (trend_pullback.detect, breakout_retest.detect):
        c = fn(ctx)
        if c is not None:
            found.append(c)

    if not found:
        return StrategyRunResult(None)

    dirs = {c.direction for c in found}
    if Direction.LONG in dirs and Direction.SHORT in dirs:
        return StrategyRunResult(
            None,
            conflict=True,
            conflict_reason="✖ Conflicting signals",
        )

    best = max(found, key=lambda c: c.pick_score)
    return StrategyRunResult(best)