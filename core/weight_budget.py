"""
Binance API weight budget (process-wide, thread-safe).
"""

from __future__ import annotations

import threading
import time

from core.config import WEIGHT_BUDGET_PER_MINUTE, WEIGHT_BUDGET_SOFT_LIMIT

_lock = threading.Lock()
_window_start = time.time()
_weight_used = 0


def _maybe_roll_window() -> None:
    global _window_start, _weight_used
    now = time.time()
    if now - _window_start >= 60.0:
        _window_start = now
        _weight_used = 0


def add_weight(used: int) -> None:
    with _lock:
        _maybe_roll_window()
        _weight_used += max(0, used)


def weight_used_this_minute() -> int:
    with _lock:
        _maybe_roll_window()
        return _weight_used


def wait_if_needed() -> None:
    """Block briefly if we're near the soft weight limit."""
    while True:
        with _lock:
            _maybe_roll_window()
            if _weight_used < WEIGHT_BUDGET_SOFT_LIMIT:
                return
        time.sleep(0.25)


def can_request(estimated_weight: int = 1) -> bool:
    with _lock:
        _maybe_roll_window()
        return _weight_used + estimated_weight <= WEIGHT_BUDGET_PER_MINUTE


def reset_for_tests() -> None:
    global _window_start, _weight_used
    with _lock:
        _window_start = time.time()
        _weight_used = 0