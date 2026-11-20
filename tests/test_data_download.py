"""Tests for backtest data download helpers (mocked HTTP)."""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.csv_klines import parse_kline_csv
from backtest.secure_io import (
    ChecksumMismatchError,
    ZipSafetyError,
    parse_checksum_file,
    safe_extract_csv,
    sha256_bytes,
    verify_checksum,
)


def _zip_csv(name: str, csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


class SecureIoTests(unittest.TestCase):
    def test_checksum_mismatch(self) -> None:
        data = b"hello"
        digest = sha256_bytes(data)
        with self.assertRaises(ChecksumMismatchError):
            verify_checksum(data, f"{digest[:-2]}00  file.zip")

    def test_zip_slip_rejected(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.csv", "1,2,3")
        with self.assertRaises(ZipSafetyError):
            safe_extract_csv(buf.getvalue(), "../evil.csv")

    def test_safe_extract_single_csv(self) -> None:
        csv = "1609459200000,1,2,3,4,5,1609459299999,6,1,2,3,0\n"
        z = _zip_csv("BTCUSDT-5m-2024-01.csv", csv)
        out = safe_extract_csv(z, "BTCUSDT-5m-2024-01.csv")
        self.assertIn(b"1609459200000", out)

    def test_parse_checksum_line(self) -> None:
        self.assertEqual(len(parse_checksum_file("abcd" + "0" * 60 + "  foo.zip")), 64)


class CsvKlinesTests(unittest.TestCase):
    def test_no_header_ms(self) -> None:
        rows = (
            "1609459200000,100,101,99,100.5,10,1609459299999,1000,1,5,500,0\n"
            "1609459500000,100.5,102,100,101,12,1609459599999,1200,1,6,600,0\n"
        )
        df = parse_kline_csv(rows)
        self.assertEqual(len(df), 2)
        self.assertEqual(int(df["close_time"].iloc[0]), 1609459299999)

    def test_header_row(self) -> None:
        rows = (
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
            "taker_buy_volume,taker_buy_quote_volume,ignore\n"
            "1609459200000,1,2,3,4,5,1609459299999,6,1,2,3,0\n"
        )
        df = parse_kline_csv(rows)
        self.assertEqual(float(df["close"].iloc[0]), 4.0)

    def test_microsecond_normalization(self) -> None:
        # µs timestamps (×1000 vs ms)
        rows = "1609459200000000,1,2,3,4,5,1609459299999000,6,1,2,3,0\n"
        df = parse_kline_csv(rows)
        self.assertEqual(int(df["close_time"].iloc[0]), 1609459299999)


class DownloadResumeTests(unittest.TestCase):
    @patch("backtest.data_download.download_verified_zip")
    def test_resume_skips_verified_month(self, mock_dl: MagicMock) -> None:
        from backtest.data_download import MonthSpec, fetch_month_klines

        manifest = {"verified_shards": {"monthly:2024-01": "abc"}}
        out = fetch_month_klines("BTCUSDT", "5m", MonthSpec(2024, 1), manifest)
        self.assertIsNone(out)
        mock_dl.assert_not_called()


if __name__ == "__main__":
    unittest.main()