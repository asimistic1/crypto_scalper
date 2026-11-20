"""Phase 2.1 fix 01 — nearest invalidation for stop-loss."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core.models import Swing, Zone
from core.setup_builder import _invalidation_level, _stop_loss_from_invalidation
from decimal import Decimal
from core.models import Direction


class NearestInvalidationTests(unittest.TestCase):
    def test_long_uses_nearest_not_farthest_low(self) -> None:
        base = datetime(2024, 1, 1, tzinfo=UTC)
        rows = []
        for i in range(60):
            t = base + timedelta(minutes=15 * i)
            rows.append({"time": t})
        ltf = pd.DataFrame(rows)

        near_low = Swing(base + timedelta(hours=10), base + timedelta(hours=10), 98.0, "low")
        far_low = Swing(base + timedelta(hours=1), base + timedelta(hours=1), 80.0, "low")
        zones = [Zone(97.5, 98.5, 98.0, 2, base, 2.0, "support")]
        entry = 100.0
        inv = _invalidation_level([near_low, far_low], zones, entry, Direction.LONG, ltf, lookback=50)
        self.assertIsNotNone(inv)
        assert inv is not None
        self.assertAlmostEqual(inv, 98.0, places=2)
        self.assertGreater(inv, 80.0)

    def test_stop_widens_to_min_risk_not_reject(self) -> None:
        tick = Decimal("0.01")
        inv = 99.95
        entry = 100.0
        atr = 1.0
        sl, risk = _stop_loss_from_invalidation(Direction.LONG, entry, inv, atr, tick)
        self.assertLess(sl, entry)
        self.assertGreaterEqual(risk, 0.5)  # SL_MIN_ATR * ATR


if __name__ == "__main__":
    unittest.main()