"""
Rate-limit cooldown tests (no live Binance calls).
Run: python tests/test_rate_limit.py
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import rate_limit
from core.data import DataFetchError, _http_get
from core.rate_limit import (
    BinanceCooldownActive,
    enter_cooldown,
    is_in_cooldown,
    record_success,
    reset_for_tests as reset_rate_limit,
    seconds_remaining,
)


class CooldownTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_rate_limit()

    def test_429_starts_cooldown_and_blocks_http(self) -> None:
        responses = [
            MagicMock(
                status_code=429,
                headers={"Retry-After": "2"},
            ),
        ]

        with patch("core.data.requests.get", return_value=responses[0]):
            with self.assertRaises(DataFetchError):
                _http_get("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})

        self.assertTrue(is_in_cooldown())
        self.assertGreaterEqual(seconds_remaining(), 1)

        with patch("core.data.requests.get") as mock_get:
            with self.assertRaises(BinanceCooldownActive):
                _http_get("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})
            mock_get.assert_not_called()

    def test_cooldown_not_reset_on_reenter_during_active(self) -> None:
        enter_cooldown(429, 60)
        until_first = time.time() + seconds_remaining()
        time.sleep(0.05)
        enter_cooldown(429, 30)
        until_second = time.time() + seconds_remaining()
        self.assertAlmostEqual(until_first, until_second, delta=2)

    def test_success_clears_cooldown(self) -> None:
        enter_cooldown(418, None)
        self.assertTrue(is_in_cooldown())
        record_success()
        self.assertFalse(is_in_cooldown())

    def test_countdown_decreases(self) -> None:
        enter_cooldown(429, 3)
        first = seconds_remaining()
        time.sleep(1.1)
        second = seconds_remaining()
        self.assertLess(second, first)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CooldownTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\nCOOLDOWN TESTS PASSED")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())