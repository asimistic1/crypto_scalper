"""Phase 2.1 fix 04 — HTF rules for trend pullback."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.models import TrendBias, TrendResult
from core.strategies._helpers import htf_allows_long, htf_allows_short, htf_not_bearish


class HtfRuleTests(unittest.TestCase):
    def test_all_neutral_not_allowed_pullback(self) -> None:
        htf = {"1h": TrendResult(TrendBias.NEUTRAL), "4h": TrendResult(TrendBias.NEUTRAL)}
        self.assertFalse(htf_allows_long(htf))
        self.assertFalse(htf_allows_short(htf))

    def test_one_bullish_ok_long(self) -> None:
        htf = {"1h": TrendResult(TrendBias.BULLISH), "4h": TrendResult(TrendBias.NEUTRAL)}
        self.assertTrue(htf_allows_long(htf))
        self.assertFalse(htf_allows_short(htf))

    def test_breakout_not_opposing(self) -> None:
        htf = {"1h": TrendResult(TrendBias.NEUTRAL), "4h": TrendResult(TrendBias.NEUTRAL)}
        self.assertTrue(htf_not_bearish(htf))


if __name__ == "__main__":
    unittest.main()