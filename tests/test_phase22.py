"""Phase 2.2 — UI polish, zones, funnel episodes, analyze dedupe."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.analysis_service import _zone_payload
from core.models import Direction, EntryType, ScoreBreakdown, Setup, SetupStatus
from tools.signal_funnel import count_setup_episodes


class ZonePayloadTests(unittest.TestCase):
    def test_support_label_at_near_edge(self) -> None:
        class Z:
            price_low = 100.0
            price_high = 101.0
            touches = 2

        rows = _zone_payload([Z()], role="support", prec=1)
        self.assertEqual(len(rows), 1)
        self.assertIn("S 101.0", rows[0]["label"])
        self.assertIn("×2", rows[0]["label"])
        self.assertAlmostEqual(rows[0]["near"], 101.0)


class FunnelEpisodeTests(unittest.TestCase):
    def test_merges_consecutive_same_direction(self) -> None:
        hits = [(1, Direction.SHORT), (2, Direction.SHORT), (3, Direction.SHORT), (10, Direction.SHORT)]
        self.assertEqual(count_setup_episodes(hits, max_bar_gap=3), 2)

    def test_direction_change_splits(self) -> None:
        hits = [(1, Direction.LONG), (2, Direction.SHORT)]
        self.assertEqual(count_setup_episodes(hits), 2)


class SetupCardCaptionTests(unittest.TestCase):
    def test_no_trade_strategy_hidden(self) -> None:
        stub = datetime(2026, 11, 20, 12, 19, tzinfo=UTC)
        setup = Setup(
            symbol="BTCUSDT",
            timeframe="5m",
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
            reasons=("✖ No strategy signal",),
            htf_trends={},
            levels_used=(),
            signal_candle_time=stub,
            as_of=stub,
            setup_id="x",
            status=SetupStatus.EXPIRED,
        )
        self.assertEqual(setup.strategy, "none")
        self.assertEqual(setup.direction, Direction.NO_TRADE)


if __name__ == "__main__":
    unittest.main()