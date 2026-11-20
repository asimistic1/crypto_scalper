"""Phase 2.1 fix 02 — take-profit ordering and net R:R gates."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.models import Direction, Zone
from core.setup_builder import _order_valid, _take_profits


class TakeProfitSelectionTests(unittest.TestCase):
    def test_long_ordering_zone_and_fallback(self) -> None:
        entry, sl = 100.0, 97.0
        zones = [
            Zone(102.5, 103.0, 102.75, 3, datetime.now(UTC), 3.0, "resistance"),
            Zone(104.0, 104.5, 104.25, 2, datetime.now(UTC), 2.0, "resistance"),
            Zone(106.0, 106.5, 106.25, 2, datetime.now(UTC), 2.0, "resistance"),
        ]
        tp1, tp2, tp3, _ = _take_profits(Direction.LONG, entry, sl, zones, 1.0, Decimal("0.01"))
        self.assertTrue(_order_valid(Direction.LONG, entry, sl, (tp1, tp2, tp3)))
        self.assertLess(entry, tp1)
        self.assertLess(tp1, tp2)
        self.assertLess(tp2, tp3)

    def test_short_ordering(self) -> None:
        entry, sl = 100.0, 102.0
        zones = [
            Zone(97.5, 98.0, 97.75, 2, datetime.now(UTC), 2.0, "support"),
            Zone(95.0, 95.5, 95.25, 2, datetime.now(UTC), 2.0, "support"),
            Zone(92.0, 92.5, 92.25, 2, datetime.now(UTC), 2.0, "support"),
        ]
        tp1, tp2, tp3, _ = _take_profits(Direction.SHORT, entry, sl, zones, 1.0, Decimal("0.01"))
        self.assertTrue(_order_valid(Direction.SHORT, entry, sl, (tp1, tp2, tp3)))
        self.assertGreater(entry, tp1)
        self.assertGreater(tp1, tp2)
        self.assertGreater(tp2, tp3)


if __name__ == "__main__":
    unittest.main()