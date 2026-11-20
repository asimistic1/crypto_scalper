"""Phase 2.1 fix 06 — stale guard in analysis_service."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.analysis_service import run_analysis
from core.candle_store import CandleFetchResult
from core.config import MIN_24H_QUOTE_VOLUME_USDT


class StaleGuardTests(unittest.TestCase):
    @patch("core.candle_store.get_many")
    def test_stale_ltf_blocks_build(self, mock_many) -> None:
        empty = pd.DataFrame()
        mock_many.return_value = {
            "15m": CandleFetchResult(df=empty, stale=True, from_cache=False),
        }
        res = run_analysis("BTC/USDT", "15m", MIN_24H_QUOTE_VOLUME_USDT * 2)
        self.assertIn("Stale", res.setup.reasons[0])


if __name__ == "__main__":
    unittest.main()