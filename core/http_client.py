"""
Shared Binance FAPI HTTP client (keep-alive, allowlist, weight + cooldown).
"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from core.rate_limit import (
    BinanceCooldownActive,
    enter_cooldown,
    is_in_cooldown,
    last_http_code,
    record_success,
    seconds_remaining,
)
from core.weight_budget import add_weight, wait_if_needed, weight_used_this_minute

ALLOWED_HOST = "fapi.binance.com"
FAPI_BASE = f"https://{ALLOWED_HOST}"

_session: requests.Session | None = None
_session_lock = threading.Lock()


def get_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            _session.mount("https://", adapter)
        return _session


def _parse_weight(headers: Any) -> int:
    raw = headers.get("X-MBX-USED-WEIGHT-1M") if headers else None
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_retry_after(headers: Any) -> int | None:
    raw = headers.get("Retry-After") if headers else None
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def fapi_get(path: str, params: dict[str, Any] | None = None) -> requests.Response:
    """
    GET against fapi.binance.com only. Raises BinanceCooldownActive when cooling down.
    """
    if is_in_cooldown():
        raise BinanceCooldownActive(seconds_remaining(), last_http_code())

    url = f"{FAPI_BASE}{path}"
    host = urlparse(url).hostname or ""
    if host != ALLOWED_HOST:
        raise ValueError(f"Host not allowed: {host}")

    wait_if_needed()
    symbol = str((params or {}).get("symbol", "—"))
    t0 = time.perf_counter()
    resp = get_session().get(url, params=params, timeout=(3, 7))
    ms = int((time.perf_counter() - t0) * 1000)
    w = _parse_weight(resp.headers)
    add_weight(w if w else 1)
    print(
        f"[binance] endpoint={path} symbol={symbol} http={resp.status_code} "
        f"weight_1m={w} duration_ms={ms} budget={weight_used_this_minute()}",
        flush=True,
    )

    if resp.status_code in (418, 429):
        enter_cooldown(resp.status_code, _parse_retry_after(resp.headers))
        resp.raise_for_status()

    if resp.status_code in (403, 451):
        resp.raise_for_status()

    resp.raise_for_status()
    record_success()
    return resp