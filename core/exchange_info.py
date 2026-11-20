"""
Cached /fapi/v1/exchangeInfo and server time offset.
"""

from __future__ import annotations

import json
import threading
import time
from decimal import Decimal
from pathlib import Path

from core.config import EXCHANGE_INFO_CACHE_HOURS, SERVER_TIME_CACHE_SECONDS
from core.http_client import fapi_get

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
_CACHE_FILE = _CACHE_DIR / "exchange_info.json"

_lock = threading.Lock()
_symbols: dict | None = None
_loaded_at: float = 0.0
_server_offset_ms: int = 0
_server_offset_at: float = 0.0


def _save_disk(payload: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")


def _load_disk() -> dict | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_symbols(data: dict) -> dict:
    out = {}
    for s in data.get("symbols", []):
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        sym = s["symbol"]
        tick = next(
            (f["tickSize"] for f in s.get("filters", []) if f.get("filterType") == "PRICE_FILTER"),
            "0.01",
        )
        step = next(
            (f["stepSize"] for f in s.get("filters", []) if f.get("filterType") == "LOT_SIZE"),
            "0.001",
        )
        out[sym] = {
            "status": s.get("status"),
            "pricePrecision": int(s.get("pricePrecision", 2)),
            "tickSize": tick,
            "stepSize": step,
        }
    return out


def refresh_exchange_info(force: bool = False) -> dict:
    global _symbols, _loaded_at
    with _lock:
        age_h = (time.time() - _loaded_at) / 3600.0
        if _symbols and not force and age_h < EXCHANGE_INFO_CACHE_HOURS:
            return _symbols

        if not force:
            disk = _load_disk()
            if disk and _symbols is None:
                _symbols = _parse_symbols(disk)
                _loaded_at = time.time()

        data = fapi_get("/fapi/v1/exchangeInfo").json()
        _save_disk(data)
        _symbols = _parse_symbols(data)
        _loaded_at = time.time()
        return _symbols


def is_valid_symbol(symbol: str) -> bool:
    sym = symbol.upper()
    meta = refresh_exchange_info().get(sym)
    return meta is not None and meta.get("status") == "TRADING"


def tick_size(symbol: str) -> Decimal:
    meta = refresh_exchange_info()[symbol.upper()]
    return Decimal(meta["tickSize"])


def price_precision(symbol: str) -> int:
    return int(refresh_exchange_info()[symbol.upper()]["pricePrecision"])


def step_size(symbol: str) -> Decimal:
    meta = refresh_exchange_info()[symbol.upper()]
    return Decimal(meta["stepSize"])


def binance_server_time_ms() -> int:
    """Binance server time in ms (cached offset 10 minutes)."""
    global _server_offset_ms, _server_offset_at
    with _lock:
        if time.time() - _server_offset_at > SERVER_TIME_CACHE_SECONDS:
            local_before = int(time.time() * 1000)
            server = int(fapi_get("/fapi/v1/time").json()["serverTime"])
            local_after = int(time.time() * 1000)
            local_mid = (local_before + local_after) // 2
            _server_offset_ms = server - local_mid
            _server_offset_at = time.time()
        return int(time.time() * 1000) + _server_offset_ms