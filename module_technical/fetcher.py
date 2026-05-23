"""
module_technical/fetcher.py
---------------------------
Fetch OHLCV candles from CoinGecko free API and resample to the requested
timeframe. Replaces the previous Binance/ccxt implementation.

Public CoinGecko endpoint (no key required, ~10-30 req/min):
    GET /api/v3/coins/{id}/market_chart?vs_currency=usd&days={days}

CoinGecko auto-selects granularity by `days`:
    days = 1       -> 5-minute points
    days = 2..90   -> hourly points       <-- used for intraday TFs
    days >= 91     -> daily points

So the maximum lookback for intraday candles is ~90 days of hourly data,
which resamples to ~540 candles at 4h or ~2160 candles at 1h. Adequate for
EMA200 and full technical analysis. For higher `limit` requests we clamp.

Optional environment:
    COINGECKO_API_KEY   Demo (free) key from https://www.coingecko.com/
                        Sent as `x-cg-demo-api-key`. Raises rate limit.
"""

import os
import time
from functools import lru_cache

import pandas as pd
import requests
from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

MIN_CANDLES   = 250
_BASE_URL     = "https://api.coingecko.com/api/v3"
_API_KEY      = os.getenv("COINGECKO_API_KEY", "").strip()
_MAX_DAYS_HR  = 90    # CoinGecko hourly cap on free tier
_REQ_TIMEOUT  = 30


# ─── Symbol → CoinGecko coin-id ────────────────────────────────────────
_COIN_ID_MAP = {
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "SOL":   "solana",
    "BNB":   "binancecoin",
    "XRP":   "ripple",
    "ADA":   "cardano",
    "DOGE":  "dogecoin",
    "AVAX":  "avalanche-2",
    "DOT":   "polkadot",
    "MATIC": "matic-network",
    "LINK":  "chainlink",
    "UNI":   "uniswap",
    "LTC":   "litecoin",
    "ATOM":  "cosmos",
    "NEAR":  "near",
    "FTM":   "fantom",
    "INJ":   "injective-protocol",
    "ARB":   "arbitrum",
    "OP":    "optimism",
    "SUI":   "sui",
    "TON":   "the-open-network",
    "TRX":   "tron",
    "SHIB":  "shiba-inu",
    "PEPE":  "pepe",
}

# Pandas resample rule per timeframe
_TF_TO_RULE = {
    "1m":  "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h":  "1h",   "2h": "2h",   "4h":  "4h",
    "6h":  "6h",   "12h":"12h",  "1d":  "1D",
}

# Approx hours per candle for sizing the lookback window
_TF_HOURS = {
    "1m": 1/60, "5m": 5/60, "15m": 0.25, "30m": 0.5,
    "1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24,
}


def _coin_id(symbol: str) -> str:
    """`BTC/USDT`, `BTCUSDT`, `btc` → `bitcoin` (coingecko id)."""
    base = (
        symbol.upper()
        .replace("/USDT", "")
        .replace("USDT", "")
        .replace("/USD", "")
        .strip()
    )
    cid = _COIN_ID_MAP.get(base)
    if cid:
        return cid
    # Fallback: lower-case base. User can extend _COIN_ID_MAP for exotic coins.
    logger.warning(f"No CoinGecko mapping for {symbol!r}; falling back to {base.lower()!r}")
    return base.lower()


def _days_needed(timeframe: str, limit: int) -> int:
    """Days of hourly data required to resample into `limit` candles of `timeframe`."""
    hours_per_candle = _TF_HOURS.get(timeframe, 4)
    total_hours = hours_per_candle * limit
    # +2 days slack to cover boundary/dropna
    days = int(total_hours / 24) + 2
    return max(2, min(days, _MAX_DAYS_HR))


@lru_cache(maxsize=128)
def _fetch_raw(coin_id: str, days: int) -> pd.DataFrame:
    """Cached hourly market_chart fetch. Returns DataFrame indexed by UTC timestamp
    with columns ['price', 'volume']."""
    url = f"{_BASE_URL}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    headers = {"accept": "application/json"}
    if _API_KEY:
        headers["x-cg-demo-api-key"] = _API_KEY

    # Simple retry loop for transient 429 / 5xx
    for attempt in range(1, 4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=_REQ_TIMEOUT)
            if r.status_code == 429:
                wait = 5 * attempt
                logger.warning(f"CoinGecko 429 rate-limited; sleeping {wait}s (attempt {attempt}/3)")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as e:
            if attempt == 3:
                raise
            logger.warning(f"CoinGecko fetch failed ({e}); retrying (attempt {attempt}/3)")
            time.sleep(3 * attempt)
    else:
        raise RuntimeError(f"CoinGecko request failed after 3 attempts: {coin_id}")

    prices  = data.get("prices") or []
    volumes = data.get("total_volumes") or []
    if not prices:
        raise RuntimeError(f"CoinGecko returned 0 datapoints for {coin_id}")

    df_p = pd.DataFrame(prices,  columns=["ts", "price"])
    df_v = pd.DataFrame(volumes, columns=["ts", "volume"])
    df_p["ts"] = pd.to_datetime(df_p["ts"], unit="ms", utc=True)
    df_v["ts"] = pd.to_datetime(df_v["ts"], unit="ms", utc=True)
    df = df_p.merge(df_v, on="ts", how="inner").set_index("ts").sort_index()
    return df


def fetch_ohlcv(symbol: str, timeframe: str = "4h", limit: int = MIN_CANDLES) -> pd.DataFrame:
    """
    Fetch OHLCV from CoinGecko and resample to `timeframe`.

    Args:
        symbol:    e.g. 'BTC/USDT' or 'BTCUSDT'
        timeframe: '1h', '4h', '1d', ...
        limit:    Approx. number of candles. Capped by 90 days of hourly src.

    Returns:
        DataFrame indexed by UTC timestamp with columns: open, high, low, close, volume.
    """
    cid    = _coin_id(symbol)
    days   = _days_needed(timeframe, limit)
    rule   = _TF_TO_RULE.get(timeframe, "4h")
    logger.info(f"CoinGecko fetch {symbol} ({cid}) days={days} → resample {timeframe}×{limit}")

    raw = _fetch_raw(cid, days)

    ohlc = raw["price"].resample(rule).ohlc()
    vol  = raw["volume"].resample(rule).sum()
    out  = ohlc.join(vol).dropna().tail(limit)
    out.index.name = "timestamp"

    if out.empty:
        raise RuntimeError(f"Empty OHLCV after resampling {timeframe} for {symbol}")

    last_close = out["close"].iloc[-1]
    logger.info(f"CoinGecko {symbol}: {len(out)} candles {timeframe}, last close {last_close:.4f}")
    return out
