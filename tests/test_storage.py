"""
Signal storage tests (Phase 2 step 7).
Run: python tests/test_storage.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.models import (
    Direction,
    EntryType,
    ScoreBreakdown,
    Setup,
    SetupStatus,
    no_trade,
)
from core.storage import init_db, reset_schema_cache_for_tests, reset_thread_connection_for_tests, save_setup


def _sample_setup(setup_id: str = "abc123") -> Setup:
    ts = datetime(2024, 9, 1, 12, 0, tzinfo=timezone.utc)
    return Setup(
        symbol="BTCUSDT",
        timeframe="15m",
        direction=Direction.LONG,
        strategy="trend_pullback",
        entry=100.0,
        entry_type=EntryType.MARKET,
        stop_loss=98.0,
        tp1=102.0,
        tp2=104.0,
        tp3=106.0,
        sl_pct=2.0,
        tp_pcts=(2.0, 4.0, 6.0),
        gross_rr=(1.0, 2.0, 3.0),
        net_rr=(0.95, 1.9, 2.8),
        score=72.0,
        breakdown=ScoreBreakdown(htf=20.0, net_rr=8.0),
        reasons=("✔ HTF aligned",),
        htf_trends={},
        levels_used=("support",),
        signal_candle_time=ts,
        as_of=ts,
        setup_id=setup_id,
        status=SetupStatus.ACTIVE,
    )


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_thread_connection_for_tests()
        reset_schema_cache_for_tests()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        os.environ["STORAGE_DB_PATH"] = str(self.db_path)

    def tearDown(self) -> None:
        reset_thread_connection_for_tests()
        reset_schema_cache_for_tests()
        os.environ.pop("STORAGE_DB_PATH", None)
        try:
            self.db_path.unlink(missing_ok=True)
        except OSError:
            pass

    def test_wal_and_schema(self) -> None:
        init_db(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode.lower(), "wal")

    def test_save_and_dedupe(self) -> None:
        setup = _sample_setup()
        self.assertTrue(save_setup(setup))
        self.assertFalse(save_setup(setup))

        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_no_trade_skipped(self) -> None:
        ts = datetime(2024, 9, 1, tzinfo=timezone.utc)
        nt = no_trade("BTCUSDT", "15m", ("✖ no",), ts)
        self.assertFalse(save_setup(nt))

    def test_json_columns(self) -> None:
        setup = _sample_setup("json01")
        save_setup(setup)
        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT breakdown_json, reasons_json FROM signals").fetchone()
        conn.close()
        bd = json.loads(row[0])
        self.assertIn("htf", bd)
        reasons = json.loads(row[1])
        self.assertEqual(reasons, ["✔ HTF aligned"])


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nSTORAGE TESTS PASSED")
    sys.exit(0 if result.wasSuccessful() else 1)