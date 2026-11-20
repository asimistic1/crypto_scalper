"""Signal prefilter and no look-ahead tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.prefilter import candidate_mask
from core.indicators import add_all_indicators


def _synth(n: int = 400) -> pd.DataFrame:
    import pandas as pd
    from datetime import UTC, datetime, timedelta

    rows = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(n):
        t = start + timedelta(minutes=15 * i)
        c = 100 + np.sin(i / 20) * 2
        rows.append(
            {
                "time": t,
                "open": c - 0.1,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 1000.0,
                "quote_volume": 100_000.0,
                "taker_buy_quote_volume": 50_000.0,
                "close_time": int((t + timedelta(minutes=14, seconds=59)).timestamp() * 1000),
            }
        )
    df = pd.DataFrame(rows)
    return add_all_indicators(df)


class PrefilterTests(unittest.TestCase):
    def test_mask_covers_enough_bars(self) -> None:
        df = _synth(500)
        mask = candidate_mask(df)
        self.assertGreater(mask.sum(), 0)
        self.assertFalse(mask[:249].any())

    def test_no_lookahead_stability(self) -> None:
        df1 = _synth(350)
        df2 = _synth(450)
        m1 = candidate_mask(df1)
        m2 = candidate_mask(df2)
        self.assertTrue(np.array_equal(m1, m2[: len(m1)]))


if __name__ == "__main__":
    unittest.main()