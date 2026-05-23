"""
module_sentiment/news_scraper.py
---------------------------------
Lấy tin tức crypto từ nhiều nguồn theo chuỗi fallback:

  1) CoinDesk Data API (yêu cầu COINDESK_API_KEY, free 100k req/tháng)
  2) RSS feeds (CoinDesk, CoinTelegraph, Decrypt) — không cần key
  3) Fallback headlines mẫu (dev/test)

Tài liệu CoinDesk: https://developers.coindesk.com/documentation/data-api/news_v1_article_list
"""

import os
import re
from typing import Iterable

import feedparser
import requests
from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

_COINDESK_KEY = os.getenv("COINDESK_API_KEY", "")
_COINDESK_URL = "https://data-api.coindesk.com/news/v1/article/list"
_MAX_HEADLINES = 30
_TIMEOUT = 15

# Map symbol → mã category CoinDesk + keyword filter RSS
SYMBOL_MAP = {
    "BTCUSDT": {"category": "BTC", "keywords": ["bitcoin", "btc"]},
    "ETHUSDT": {"category": "ETH", "keywords": ["ethereum", "eth", "vitalik"]},
    "SOLUSDT": {"category": "SOL", "keywords": ["solana", "sol"]},
    "BNBUSDT": {"category": "BNB", "keywords": ["bnb", "binance coin"]},
    "XRPUSDT": {"category": "XRP", "keywords": ["xrp", "ripple"]},
}

_RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
]


# ─────────────────────────────────────────────────────────────
# Nguồn 1: CoinDesk Data API
# ─────────────────────────────────────────────────────────────

def _fetch_coindesk(symbol: str, limit: int) -> list[str]:
    """Lấy tin từ CoinDesk Data API."""
    if not _COINDESK_KEY or _COINDESK_KEY.startswith("your_"):
        return []

    info = SYMBOL_MAP.get(symbol.upper(), {})
    category = info.get("category", symbol.upper().replace("USDT", ""))

    params = {
        "lang": "EN",
        "limit": min(limit, 100),
        "categories": category,
        "api_key": _COINDESK_KEY,
    }

    try:
        r = requests.get(_COINDESK_URL, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        articles = data.get("Data", [])
        headlines = [a.get("TITLE", "").strip() for a in articles if a.get("TITLE")]
        if headlines:
            logger.info(f"[CoinDesk API] {symbol}: {len(headlines)} tiêu đề")
        return headlines
    except Exception as e:
        logger.warning(f"[CoinDesk API] Lỗi cho {symbol}: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# Nguồn 2: RSS feeds (không cần key)
# ─────────────────────────────────────────────────────────────

def _fetch_rss(symbol: str, limit: int) -> list[str]:
    """Lấy tin từ RSS, lọc theo keyword của symbol."""
    info = SYMBOL_MAP.get(symbol.upper(), {})
    keywords = [k.lower() for k in info.get("keywords", [symbol.lower().replace("usdt", "")])]

    headlines: list[str] = []
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)

    for feed_url in _RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:50]:
                title = (entry.get("title") or "").strip()
                if title and pattern.search(title):
                    headlines.append(title)
                if len(headlines) >= limit:
                    break
        except Exception as e:
            logger.warning(f"[RSS] Lỗi {feed_url}: {e}")
        if len(headlines) >= limit:
            break

    if headlines:
        logger.info(f"[RSS] {symbol}: {len(headlines)} tiêu đề")
    return headlines[:limit]


# ─────────────────────────────────────────────────────────────
# Fallback: dữ liệu mẫu cho dev
# ─────────────────────────────────────────────────────────────

def _dedupe(seq: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for s in seq:
        key = s.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def fetch_news(symbol: str, limit: int = _MAX_HEADLINES) -> list[str]:
    """
    Lấy tiêu đề tin tức mới nhất cho symbol.
    Kết hợp CoinDesk API + RSS, dedupe theo tiêu đề.
    """
    headlines: list[str] = []

    # 1) CoinDesk API
    headlines += _fetch_coindesk(symbol, limit)

    # 2) RSS (nếu CoinDesk chưa đủ hoặc fail)
    if len(headlines) < limit:
        rss_items = _fetch_rss(symbol, limit - len(headlines))
        headlines += rss_items

    headlines = _dedupe(headlines)[:limit]

    if not headlines:
        return _get_fallback_headlines(symbol)

    logger.info(f"Tổng cộng {len(headlines)} tiêu đề tin cho {symbol}")
    return headlines


def _get_fallback_headlines(symbol: str) -> list[str]:
    """Trả về dữ liệu mẫu khi không có API key (dùng cho dev/test)."""
    logger.warning(f"Dùng tiêu đề mẫu cho {symbol} (không lấy được tin thực)")
    return [
        f"{symbol} shows strong bullish momentum amid market rally",
        f"Institutional investors increasing {symbol} holdings",
        f"{symbol} price prediction: analysts bullish for next quarter",
        f"Market sentiment improves as {symbol} recovers key support",
        f"{symbol} trading volume surges to monthly high",
    ]
