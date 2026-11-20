"""Phase 2.1 fix 03 — zone roles vs price and recency."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from core.levels import build_zones
from core.models import Swing


def _df(n: int) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "time": [start + timedelta(minutes=15 * i) for i in range(n)],
            "close": [100.0 + i * 0.1 for i in range(n)],
        }
    )


class ZoneRoleTests(unittest.TestCase):
    def test_broken_support_becomes_resistance(self) -> None:
        df = _df(80)
        ref = 104.0
        low = Swing(df["time"].iloc[10].to_pydatetime(), df["time"].iloc[15].to_pydatetime(), 105.0, "low")
        zones = build_zones([low], 1.0, reference_price=ref, df=df, as_of=df["time"].iloc[-1].to_pydatetime())
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].role, "resistance")
        self.assertTrue(zones[0].flipped)

    def test_fresh_zone_stronger_than_old(self) -> None:
        df = _df(200)
        ref = 100.0
        old = Swing(df["time"].iloc[5].to_pydatetime(), df["time"].iloc[10].to_pydatetime(), 98.0, "low")
        fresh = Swing(df["time"].iloc[180].to_pydatetime(), df["time"].iloc[185].to_pydatetime(), 98.1, "low")
        z_old = build_zones([old], 1.0, reference_price=ref, df=df, as_of=df["time"].iloc[-1].to_pydatetime())
        z_both = build_zones([old, fresh], 1.0, reference_price=ref, df=df, as_of=df["time"].iloc[-1].to_pydatetime())
        self.assertGreater(z_both[0].strength, z_old[0].strength)


if __name__ == "__main__":
    unittest.main()