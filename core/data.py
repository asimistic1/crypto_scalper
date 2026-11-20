"""
Fetch public market data from Binance USDT-M perpetual futures via ccxt.
No API keys required for candles and ticker data.

The Streamlit app must call bind_exchange() with a @st.cache_resource client
so load_markets() runs only once per server process.
"""

from __future__ import annotations

import os
import time

import ccxt
import pandas as pd
import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# USDT-M futures public REST (low API weight — good for shared Render IPs).
FAPI_BASE = "https://fapi.binance.com"

PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

# Hardcoded sidebar fallback when fetch_tickers() is rate-limited or fails.
TOP_SYMBOLS_FALLBACK = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
]

# Active client — set from streamlit_app.cached_binance_exchange().
_active_exchange: ccxt.binanceusdm | None = None
_proxy_url: str | None = None


def load_proxy_from_env() -> str | None:
    """Read optional HTTPS proxy from .env (never log — may contain credentials)."""
    load_dotenv()
    for key in ("BINANCE_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def use_lightweight_binance() -> bool:
    """
    On Render/shared hosts, skip ccxt load_markets + fetch_tickers (very heavy).
    Set BINANCE_LIGHTWEIGHT=0 to force ccxt even on Render.
    """
    load_dotenv()
    flag = os.getenv("BINANCE_LIGHTWEIGHT", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return os.getenv("RENDER", "").strip().lower() == "true"


def configure_network(proxy_url: str | None = None) -> None:
    """Remember proxy URL for create_binance_exchange(); clears active client."""
    global _active_exchange, _proxy_url
    normalized = proxy_url.strip() if proxy_url else None
    if normalized != _proxy_url:
        _proxy_url = normalized
        _active_exchange = None


def create_binance_exchange(proxy_url: str | None = None) -> ccxt.binanceusdm:
    """
    Build one Binance USDT-M client and load linear futures markets a single time.
    Call from @st.cache_resource in the Streamlit app (once per server boot).
    """
    config: dict = {
        "enableRateLimit": True,
        "options": {
            # Lighter market metadata — USDT-M linear only (skip spot / inverse).
            "defaultType": "future",
            "fetchMarkets": ["linear"],
        },
    }
    if proxy_url:
        config["proxies"] = {"http": proxy_url, "https": proxy_url}

    exchange = ccxt.binanceusdm(config)
    # Single heavy REST burst; later calls reuse exchange.markets in memory.
    exchange.load_markets()
    return exchange


def bind_exchange(exchange: ccxt.binanceusdm) -> None:
    """Attach the cached Streamlit exchange instance for all data helpers."""
    global _active_exchange
    _active_exchange = exchange


def get_exchange() -> ccxt.binanceusdm:
    """
    Return the bound exchange (preferred) or create one for scripts/tests.
    """
    global _active_exchange
    if _active_exchange is None:
        _active_exchange = create_binance_exchange(_proxy_url)
    return _active_exchange


def _is_region_block_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "451" in text or "403" in text or "restricted location" in text


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "418" in text
        or "-1003" in text
        or "too many requests" in text
        or "way too many" in text
    )


def region_block_user_message() -> str:
    return (
        "Binance is blocking this server’s region (very common on Streamlit Cloud US "
        "hosts). Running on your PC may still work."
    )


def rate_limit_user_message(retry_seconds: int = 60) -> str:
    return (
        f"Binance rate limit (HTTP 418/429). Shared server IPs hit limits quickly. "
        f"Wait ~{retry_seconds}s, then click Analyze — cached data may still load."
    )


def is_rate_limit_message(msg: str | None) -> bool:
    if not msg:
        return False
    lower = msg.lower()
    return "rate limit" in lower or "418" in lower or "429" in lower or "-1003" in lower


def region_block_help_markdown() -> str:
    return """**Why this happens**  
Streamlit Community Cloud runs in US/EU data centers. Binance **USDT-M Futures**
API often refuses those IP addresses (HTTP 451 / 403). That is not a bug in your code.

**What usually works**

1. **Use the app on your PC** — `streamlit run streamlit_app.py` (your home IP is often allowed).
2. **Self-host Streamlit** on a small VPS in Asia/Middle East/Europe (not US), then run the same repo there.
3. **Optional proxy** — In [Streamlit app settings → Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
   add a proxy in an allowed region (paid service; you are responsible for compliance):

```toml
BINANCE_HTTPS_PROXY = "http://USER:PASS@proxy-host:PORT"
```

Reboot the app after saving secrets. Never commit real proxy credentials to GitHub.
"""


def _region_block_message() -> str:
    return region_block_user_message()


def _map_api_error(exc: BaseException) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if exc.response.status_code in (418, 429):
            return rate_limit_user_message()
        if exc.response.status_code in (403, 451):
            return _region_block_message()
    if _is_region_block_error(exc):
        return _region_block_message()
    if _is_rate_limit_error(exc):
        return rate_limit_user_message()
    return str(exc)


def symbol_to_rest_id(ccxt_symbol: str) -> str:
    """BTC/USDT:USDT -> BTCUSDT for Binance fapi paths."""
    base = ccxt_symbol.split(":")[0].replace("/", "")
    return base


def _request_proxies() -> dict[str, str] | None:
    if not _proxy_url:
        return None
    return {"http": _proxy_url, "https": _proxy_url}


def _http_get(path: str, params: dict) -> requests.Response:
    """Single GET to fapi.binance.com with optional proxy."""
    url = f"{FAPI_BASE}{path}"
    resp = requests.get(
        url, params=params, timeout=25, proxies=_request_proxies()
    )
    if resp.status_code in (418, 429):
        raise ccxt.ExchangeError(
            f"HTTP {resp.status_code}: way too many requests (-1003)"
        )
    if resp.status_code in (403, 451):
        raise ccxt.ExchangeError(f"HTTP {resp.status_code}: restricted location")
    resp.raise_for_status()
    return resp


def _get_candles_rest(
    symbol: str, timeframe: str, limit: int
) -> tuple[pd.DataFrame | None, str | None]:
    """Low-weight klines endpoint (no ccxt, no load_markets)."""
    try:
        rest_sym = symbol_to_rest_id(symbol)
        data = _http_get(
            "/fapi/v1/klines",
            {"symbol": rest_sym, "interval": timeframe, "limit": limit},
        ).json()
        if not data:
            return None, "No candle data returned from the exchange."

        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "_c6",
                "_c7",
                "_c8",
                "_c9",
                "_c10",
                "_c11",
            ],
        )
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

        df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(
            PAKISTAN_TZ
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        now_ms = int(time.time() * 1000)
        period_ms = _timeframe_ms(timeframe)
        last_open_ms = int(df["timestamp"].iloc[-1])
        df["is_closed"] = True
        df.loc[df.index[-1], "is_closed"] = (now_ms - last_open_ms) >= period_ms
        df = df.drop(columns=["timestamp"])
        return df, None
    except requests.RequestException as e:
        return None, f"Network error while fetching candles: {_map_api_error(e)}"
    except ccxt.ExchangeError as e:
        return None, f"Exchange error while fetching candles: {_map_api_error(e)}"
    except Exception as e:
        return None, f"Unexpected error while fetching candles: {_map_api_error(e)}"


def _get_ticker_rest(symbol: str) -> tuple[dict | None, str | None]:
    """Single-symbol 24h ticker (weight 1) instead of fetch_ticker via ccxt."""
    try:
        rest_sym = symbol_to_rest_id(symbol)
        t = _http_get("/fapi/v1/ticker/24hr", {"symbol": rest_sym}).json()
        last = float(t.get("lastPrice") or 0)
        pct = float(t.get("priceChangePercent") or 0)
        return (
            {
                "last": last,
                "change_pct": pct,
                "high_24h": float(t.get("highPrice") or 0),
                "low_24h": float(t.get("lowPrice") or 0),
                "quote_volume_24h": float(t.get("quoteVolume") or 0),
            },
            None,
        )
    except requests.RequestException as e:
        mapped = _map_api_error(e)
        return None, f"Network error while fetching ticker: {mapped}"
    except ccxt.ExchangeError as e:
        mapped = _map_api_error(e)
        return None, f"Exchange error while fetching ticker: {mapped}"
    except Exception as e:
        return None, f"Unexpected error while fetching ticker: {_map_api_error(e)}"


def _timeframe_ms(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    if unit not in multipliers:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return value * multipliers[unit]


def get_candles(
    symbol: str, timeframe: str, limit: int = 500
) -> tuple[pd.DataFrame | None, str | None]:
    """
    Download OHLCV candles (use streamlit @st.cache_data on this — ttl ~15s).

    Returns (dataframe, error_message). On success error_message is None.
    """
    if use_lightweight_binance():
        return _get_candles_rest(symbol, timeframe, limit)

    try:
        exchange = get_exchange()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            return None, "No candle data returned from the exchange."

        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(
            PAKISTAN_TZ
        )

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        now_ms = exchange.milliseconds()
        period_ms = _timeframe_ms(timeframe)
        last_open_ms = int(df["timestamp"].iloc[-1])
        df["is_closed"] = True
        df.loc[df.index[-1], "is_closed"] = (now_ms - last_open_ms) >= period_ms

        df = df.drop(columns=["timestamp"])
        return df, None

    except ccxt.NetworkError as e:
        return None, f"Network error while fetching candles: {_map_api_error(e)}"
    except ccxt.ExchangeError as e:
        return None, f"Exchange error while fetching candles: {_map_api_error(e)}"
    except Exception as e:
        return None, f"Unexpected error while fetching candles: {_map_api_error(e)}"


def get_ticker(symbol: str) -> tuple[dict | None, str | None]:
    """24h ticker — cache in the app with a short TTL to limit REST calls."""
    if use_lightweight_binance():
        return _get_ticker_rest(symbol)

    try:
        exchange = get_exchange()
        t = exchange.fetch_ticker(symbol)
        last = float(t.get("last") or 0)
        pct = t.get("percentage")
        if pct is None and t.get("open") and last:
            open_ = float(t["open"])
            if open_:
                pct = ((last - open_) / open_) * 100.0
        return (
            {
                "last": last,
                "change_pct": float(pct) if pct is not None else 0.0,
                "high_24h": float(t.get("high") or 0),
                "low_24h": float(t.get("low") or 0),
                "quote_volume_24h": float(t.get("quoteVolume") or 0),
            },
            None,
        )
    except ccxt.NetworkError as e:
        mapped = _map_api_error(e)
        if _is_rate_limit_error(e):
            return None, mapped
        return None, f"Network error while fetching ticker: {mapped}"
    except ccxt.ExchangeError as e:
        mapped = _map_api_error(e)
        if _is_rate_limit_error(e):
            return None, mapped
        return None, f"Exchange error while fetching ticker: {mapped}"
    except Exception as e:
        mapped = _map_api_error(e)
        return None, f"Unexpected error while fetching ticker: {mapped}"


def _display_symbol(ccxt_symbol: str) -> str:
    base = ccxt_symbol.split(":")[0]
    return base


def get_top_symbols(
    n: int = 30, *, fetch_volume_ranking: bool = False
) -> tuple[list[str], str | None]:
    """
    Top USDT perpetuals by 24h quote volume.
    On Render (lightweight mode) returns the static list unless fetch_volume_ranking=True.
    """
    if use_lightweight_binance() and not fetch_volume_ranking:
        return list(TOP_SYMBOLS_FALLBACK), None

    try:
        exchange = get_exchange()
        tickers = exchange.fetch_tickers()
        candidates: list[tuple[float, str]] = []

        for market_id, ticker in tickers.items():
            try:
                market = exchange.market(market_id)
            except Exception:
                continue
            if not market.get("swap"):
                continue
            if market.get("quote") != "USDT":
                continue
            vol = float(ticker.get("quoteVolume") or 0)
            if vol <= 0:
                continue
            candidates.append((vol, market_id))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = [_display_symbol(sym) for _, sym in candidates[:n]]
        if not any(s.startswith("BTC/") for s in top) and "BTC/USDT:USDT" in tickers:
            top.insert(0, "BTC/USDT")
        return top, None

    except (ccxt.NetworkError, ccxt.ExchangeError, Exception) as e:
        if _is_rate_limit_error(e):
            return list(TOP_SYMBOLS_FALLBACK), rate_limit_user_message()
        if _is_region_block_error(e):
            return list(TOP_SYMBOLS_FALLBACK), _region_block_message()
        return list(TOP_SYMBOLS_FALLBACK), f"Could not load symbol list: {_map_api_error(e)}"


def display_to_ccxt_symbol(display: str) -> str:
    if ":" in display:
        return display
    return f"{display}:USDT"