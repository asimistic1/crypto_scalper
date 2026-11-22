"""Watchlist mini-ticker component — single Binance WS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND = Path(__file__).resolve().parent.parent / "components" / "mini_ticker" / "frontend"
_MINI = components.declare_component("mini_ticker", path=str(_FRONTEND))
_KEY = "mini_ticker_ws"


def render_mini_ticker(symbols: list[str]) -> Any:
    syms = [s.upper() for s in symbols if s][:50]
    return _MINI(symbols=syms, key=_KEY, default=None)