"""
Process-wide Binance cooldown (shared by all Streamlit users on one server).
"""

from __future__ import annotations

import threading
import time

# Exponential backoff when Retry-After is missing: 30 → 60 → 120 → 300 (cap).
BACKOFF_SECONDS = [30, 60, 120, 300]
BAN_418_MIN_SECONDS = 300

_lock = threading.Lock()
_cooldown_until: float = 0.0
_last_http_code: int | None = None
_backoff_index: int = 0


class BinanceCooldownActive(Exception):
    """Raised when we skip a network call because the server is in cooldown."""

    def __init__(self, remaining_seconds: int, http_code: int | None = None) -> None:
        self.remaining_seconds = remaining_seconds
        self.http_code = http_code
        super().__init__(f"cooldown {remaining_seconds}s HTTP {http_code}")


def is_in_cooldown() -> bool:
    with _lock:
        return time.time() < _cooldown_until


def seconds_remaining() -> int:
    with _lock:
        return max(0, int(_cooldown_until - time.time()))


def last_http_code() -> int | None:
    with _lock:
        return _last_http_code


def banner_message() -> str:
    """User-facing banner with decreasing countdown (recompute each rerun)."""
    code = last_http_code() or 429
    remaining = seconds_remaining()
    return f"Binance rate limit (HTTP {code}) — retrying in {remaining}s"


def enter_cooldown(http_code: int, retry_after: int | None = None) -> None:
    """
    Start or extend cooldown only if we are not already waiting.
    HTTP 418 (IP ban) uses at least 300 seconds.
    """
    global _cooldown_until, _last_http_code, _backoff_index
    with _lock:
        now = time.time()
        if now < _cooldown_until:
            return

        if http_code == 418:
            wait = max(BAN_418_MIN_SECONDS, retry_after or 0)
        elif retry_after is not None and retry_after > 0:
            wait = min(retry_after, BACKOFF_SECONDS[-1])
        else:
            wait = BACKOFF_SECONDS[min(_backoff_index, len(BACKOFF_SECONDS) - 1)]
            _backoff_index = min(_backoff_index + 1, len(BACKOFF_SECONDS) - 1)

        wait = min(max(wait, 1), BACKOFF_SECONDS[-1])
        _cooldown_until = now + wait
        _last_http_code = http_code


def record_success() -> None:
    """Clear cooldown after any successful Binance response."""
    global _cooldown_until, _last_http_code, _backoff_index
    with _lock:
        _cooldown_until = 0.0
        _last_http_code = None
        _backoff_index = 0


def reset_for_tests() -> None:
    """Testing only — clear module state."""
    global _cooldown_until, _last_http_code, _backoff_index
    with _lock:
        _cooldown_until = 0.0
        _last_http_code = None
        _backoff_index = 0