"""
Candle store unit tests (mocked HTTP).
Run: python tests/test_candle_store.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.candle_store import _drop_unclosed, _integrity_ok, _klines_to_df, get_closed_candles, reset_for_tests
from core.rate_limit import BinanceCooldownActive, enter_cooldown, reset_for_tests as reset_rl


def _make_kline(open_ms: int, close_ms: int, close: float) -> list:
    return [open_ms, close, close, close, close, 100.0, close_ms, 0, 0, 0, 0, 0]


class CandleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()
        reset_rl()

    @patch("core.candle_store.binance_server_time_ms", return_value=1_000_000_000)
    def test_drop_unclosed(self, _mock_time: MagicMock) -> None:
        raw = [_make_kline(100, 200, 1.0), _make_kline(300, 999_999_999_000, 2.0)]
        df = _klines_to_df(raw)
        closed = _drop_unclosed(df, "15m")
        self.assertEqual(len(closed), 1)

    def test_integrity_detects_gap(self) -> None:
        times = pd.to_datetime([0, 1_800_000], unit="ms", utc=True)
        df = pd.DataFrame(
            {
                "time": times,
                "open": [1.0, 1.0],
                "high": [1.0, 1.0],
                "low": [1.0, 1.0],
                "close": [1.0, 1.0],
                "volume": [1.0, 1.0],
                "close_time": [899_999, 2_699_999],
            }
        )
        self.assertFalse(_integrity_ok(df, "15m"))

    @patch("core.candle_store.fapi_get")
    @patch("core.candle_store.binance_server_time_ms", return_value=2_000_000)
    def test_cooldown_blocks_fetch(self, _t: MagicMock, mock_get: MagicMock) -> None:
        enter_cooldown(429, 60)
        with self.assertRaises(BinanceCooldownActive):
            get_closed_candles("BTCUSDT", "15m", full=True)
        mock_get.assert_not_called()

    @patch("core.candle_store.fapi_get")
    @patch("core.candle_store.binance_server_time_ms", return_value=3_600_000)
    def test_incremental_append(self, _t: MagicMock, mock_get: MagicMock) -> None:
        base = [_make_kline(0, 899_999, 1.0)]
        nxt = [_make_kline(900_000, 1_799_999, 2.0)]
        mock_get.side_effect = [
            MagicMock(json=lambda: base),
            MagicMock(json=lambda: nxt),
        ]
        r1 = get_closed_candles("BTCUSDT", "15m", full=True)
        self.assertEqual(len(r1.df), 1)
        r2 = get_closed_candles("BTCUSDT", "15m")
        self.assertEqual(len(r2.df), 2)
        self.assertEqual(mock_get.call_count, 2)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CandleStoreTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\nCANDLE STORE TESTS PASSED")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())