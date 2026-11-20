"""Phase 2.1 fix 07 — score ceiling and structured candidate scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import SCORE_WEIGHTS
from core.models import ScoreBreakdown


class ScoreMaxTests(unittest.TestCase):
    def test_breakdown_total_capped_at_100(self) -> None:
        w = SCORE_WEIGHTS
        bd = ScoreBreakdown(
            htf=float(w.htf),
            level_quality=float(w.level_quality),
            momentum=float(w.momentum),
            volume=float(w.volume),
            candle_confirmation=float(w.candle_confirmation),
            net_rr=float(w.net_rr),
            volatility=float(w.volatility),
            penalties=0.0,
        )
        self.assertLessEqual(bd.total, 100.0)
        self.assertGreaterEqual(bd.total, 95.0)


if __name__ == "__main__":
    unittest.main()