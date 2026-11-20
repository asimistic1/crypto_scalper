"""
Fetch public market data from Binance USDT-M perpetual futures via ccxt or lightweight REST.
"""

from __future__ import annotations

import os
import time
from typing import Any

import ccxt
import pandas as pd
import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from core.rate_limit import BinanceCooldownActive, enter_cooldown, is_in_cooldown, record_success, seconds_remaining, last_http_code

FAPI_BASE = "https://fapi.binance.com"
PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

TOP_SYMBOLS_FALLBACK = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
]

_active_exchange: ccxt.binanceusdm | None = None
_proxy_url: str | None = None


class DataFetchError(Exception):
    """Non-cooldown fetch failure with a friendly message."""

    def __init__(self, message: str, http_code: int | None = None) -> None:
        self.message = message
        self.http_code = http_code
        super().__init__(message)


def load_proxy_from_env() -> str | None:
    load_dotenv()
    for key in ("BINANCE_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def use_lightweight_binance() -> bool:
    load_dotenv()
    flag = os.getenv("BINANCE_LIGHTWEIGHT", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return os.getenv("RENDER", "").strip().lower() == "true"


def configure_network(proxy_url: str | None = None) -> None:
    global _active_exchange, _proxy_url
    normalized = proxy_url.strip() if proxy_url else None
    if normalized != _proxy_url:
        _proxy_url = normalized
        _active_exchange = None


def create_binance_exchange(proxy_url: str | None = None) -> ccxt.binanceusdm:
    if is_in_cooldown():
        raise BinanceCooldownActive(seconds_remaining(), last_http_code())
    config: dict = {
        "enableRateLimit": True,
        "options": {"defaultType": "future", "fetchMarkets": ["linear"]},
    }
    if proxy_url:
        config["proxies"] = {"http": proxy_url, "https": proxy_url}
    exchange = ccxt.binanceusdm(config)
    exchange.load_markets()
    record_success()
    return exchange


def bind_exchange(exchange: ccxt.binanceusdm) -> None:
    global _active_exchange
    _active_exchange = exchange


def get_exchange() -> ccxt.binanceusdm:
    global _active_exchange
    if is_in_cooldown():
        raise BinanceCooldownActive(seconds_remaining(), last_http_code())
    if _active_exchange is None:
        _active_exchange = create_binance_exchange(_proxy_url)
    return _active_exchange


def region_block_user_message() -> str:
    return (
        "Binance is blocking this server’s region (very common on Streamlit Cloud US "
        "hosts). Running on your PC may still work."
    )


def is_rate_limit_message(msg: str | None) -> bool:
    if not msg:
        return False
    lower = msg.lower()
    return "rate limit" in lower or "418" in lower or "429" in lower or "cooldown" in lower


def region_block_help_markdown() -> str:
    return """**Why this happens**  
Streamlit Community Cloud runs in US/EU data centers. Binance **USDT-M Futures**
API often refuses those IP addresses (HTTP 451 / 403). That is not a bug in your code.

**What usually works**

1. **Use the app on your PC** — `streamlit run streamlit_app.py`
2. **Self-host** on a VPS outside the US
3. **Optional proxy** in Streamlit secrets: `BINANCE_HTTPS_PROXY`
"""


def symbol_to_rest_id(ccxt_symbol: str) -> str:
    return ccxt_symbol.split(":")[0].replace("/", "")


def _request_proxies() -> dict[str, str] | None:
    if not _proxy_url:
        return None
    return {"http": _proxy_url, "https": _proxy_url}


def _parse_retry_after(response: requests.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _log_binance_request(path: str, symbol: str, status: int, headers: Any) -> None:
    weight = headers.get("X-MBX-USED-WEIGHT-1M", "?") if headers else "?"
    print(
        f"[binance] endpoint={path} symbol={symbol} http={status} weight_1m={weight}",
        flush=True,
    )


def _http_get(path: str, params: dict) -> requests.Response:
    if is_in_cooldown():
        raise BinanceCooldownActive(seconds_remaining(), last_http_code())

    symbol = str(params.get("symbol", "—"))
    url = f"{FAPI_BASE}{path}"
    resp = requests.get(url, params=params, timeout=25, proxies=_request_proxies())
    _log_binance_request(path, symbol, resp.status_code, resp.headers)

    if resp.status_code in (418, 429):
        retry_after = _parse_retry_after(resp)
        enter_cooldown(resp.status_code, retry_after)
        raise DataFetchError(
            f"Binance rate limit HTTP {resp.status_code}",
            http_code=resp.status_code,
        )
    if resp.status_code in (403, 451):
        raise DataFetchError(region_block_user_message(), http_code=resp.status_code)

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        code = resp.status_code
        raise DataFetchError(f"HTTP {code}: {exc}", http_code=code) from exc

    record_success()
    return resp


def _timeframe_ms(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    if unit not in multipliers:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return value * multipliers[unit]


def _ohlcv_frame_from_rows(raw: list, timeframe: str) -> pd.DataFrame:
    df = pd.DataFrame(
        raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(PAKISTAN_TZ)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    now_ms = int(time.time() * 1000)
    period_ms = _timeframe_ms(timeframe)
    last_open_ms = int(df["timestamp"].iloc[-1])
    df["is_closed"] = True
    df.loc[df.index[-1], "is_closed"] = (now_ms - last_open_ms) >= period_ms
    return df.drop(columns=["timestamp"])


def fetch_ohlcv_dataframe(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Cached callers should use this — raises on failure (never cache errors).
    """
    if use_lightweight_binance():
        rest_sym = symbol_to_rest_id(symbol)
        data = _http_get(
            "/fapi/v1/klines",
            {"symbol": rest_sym, "interval": timeframe, "limit": limit},
        ).json()
        if not data:
            raise DataFetchError("No candle data returned from the exchange.")
        return _ohlcv_frame_from_rows(
            [[int(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in data],
            timeframe,
        )

    try:
        exchange = get_exchange()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            raise DataFetchError("No candle data returned from the exchange.")
        record_success()
        return _ohlcv_frame_from_rows(raw, timeframe)
    except BinanceCooldownActive:
        raise
    except DataFetchError:
        raise
    except ccxt.NetworkError as e:
        _maybe_ccxt_rate_limit(e)
        raise DataFetchError(f"Network error while fetching candles: {e}") from e
    except ccxt.ExchangeError as e:
        _maybe_ccxt_rate_limit(e)
        raise DataFetchError(f"Exchange error while fetching candles: {e}") from e


def fetch_ticker_dict(symbol: str) -> dict:
    """24h stats for one symbol — raises on failure."""
    if use_lightweight_binance():
        rest_sym = symbol_to_rest_id(symbol)
        t = _http_get("/fapi/v1/ticker/24hr", {"symbol": rest_sym}).json()
        last = float(t.get("lastPrice") or 0)
        return {
            "last": last,
            "change_pct": float(t.get("priceChangePercent") or 0),
            "high_24h": float(t.get("highPrice") or 0),
            "low_24h": float(t.get("lowPrice") or 0),
            "quote_volume_24h": float(t.get("quoteVolume") or 0),
        }

    try:
        exchange = get_exchange()
        t = exchange.fetch_ticker(symbol)
        record_success()
        last = float(t.get("last") or 0)
        pct = t.get("percentage")
        if pct is None and t.get("open") and last:
            open_ = float(t["open"])
            if open_:
                pct = ((last - open_) / open_) * 100.0
        return {
            "last": last,
            "change_pct": float(pct) if pct is not None else 0.0,
            "high_24h": float(t.get("high") or 0),
            "low_24h": float(t.get("low") or 0),
            "quote_volume_24h": float(t.get("quoteVolume") or 0),
        }
    except BinanceCooldownActive:
        raise
    except DataFetchError:
        raise
    except ccxt.NetworkError as e:
        _maybe_ccxt_rate_limit(e)
        raise DataFetchError(f"Network error while fetching ticker: {e}") from e
    except ccxt.ExchangeError as e:
        _maybe_ccxt_rate_limit(e)
        raise DataFetchError(f"Exchange error while fetching ticker: {e}") from e


def _maybe_ccxt_rate_limit(exc: BaseException) -> None:
    text = str(exc).lower()
    code = 418 if "418" in text else (429 if "429" in text or "-1003" in text else None)
    if code is not None:
        enter_cooldown(code, None)


def _is_region_block_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "451" in text or "403" in text or "restricted location" in text


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "418" in text or "-1003" in text or "too many requests" in text


# --- Legacy tuple API for tests/scripts ---


def get_candles(
    symbol: str, timeframe: str, limit: int = 500
) -> tuple[pd.DataFrame | None, str | None]:
    try:
        return fetch_ohlcv_dataframe(symbol, timeframe, limit), None
    except BinanceCooldownActive as e:
        return None, f"Binance cooldown active ({e.remaining_seconds}s)"
    except DataFetchError as e:
        return None, e.message


def get_ticker(symbol: str) -> tuple[dict | None, str | None]:
    try:
        return fetch_ticker_dict(symbol), None
    except BinanceCooldownActive as e:
        return None, f"Binance cooldown active ({e.remaining_seconds}s)"
    except DataFetchError as e:
        return None, e.message


def _display_symbol(ccxt_symbol: str) -> str:
    return ccxt_symbol.split(":")[0]


def fetch_top_symbols_list(n: int = 30, *, fetch_volume_ranking: bool = False) -> list[str]:
    """Raises on failure; used behind @st.cache_data."""
    if use_lightweight_binance() and not fetch_volume_ranking:
        return list(TOP_SYMBOLS_FALLBACK)

    exchange = get_exchange()
    tickers = exchange.fetch_tickers()
    record_success()
    candidates: list[tuple[float, str]] = []
    for market_id, ticker in tickers.items():
        try:
            market = exchange.market(market_id)
        except Exception:
            continue
        if not market.get("swap") or market.get("quote") != "USDT":
            continue
        vol = float(ticker.get("quoteVolume") or 0)
        if vol > 0:
            candidates.append((vol, market_id))
    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [_display_symbol(sym) for _, sym in candidates[:n]]
    if not any(s.startswith("BTC/") for s in top) and "BTC/USDT:USDT" in tickers:
        top.insert(0, "BTC/USDT")
    return top


def get_top_symbols(
    n: int = 30, *, fetch_volume_ranking: bool = False
) -> tuple[list[str], str | None]:
    try:
        return fetch_top_symbols_list(n, fetch_volume_ranking=fetch_volume_ranking), None
    except BinanceCooldownActive as e:
        return list(TOP_SYMBOLS_FALLBACK), f"Binance cooldown ({e.remaining_seconds}s)"
    except DataFetchError as e:
        return list(TOP_SYMBOLS_FALLBACK), e.message
    except Exception as e:
        if _is_rate_limit_error(e):
            return list(TOP_SYMBOLS_FALLBACK), str(e)
        if _is_region_block_error(e):
            return list(TOP_SYMBOLS_FALLBACK), region_block_user_message()
        return list(TOP_SYMBOLS_FALLBACK), str(e)


def display_to_ccxt_symbol(display: str) -> str:
    if ":" in display:
        return display
    return f"{display}:USDT"