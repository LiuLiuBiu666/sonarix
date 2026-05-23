"""
module_sentiment/main_sentiment.py
------------------------------------
Điểm vào chính của luồng phân tích tâm lý.
Lấy tin tức → gửi Gemini → lưu điểm vào Supabase.

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_sentiment.main_sentiment
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from core_shared.database import get_client
from core_shared.logger import get_logger
from module_sentiment.gemini_analyzer import analyze_sentiment
from module_sentiment.news_scraper import fetch_news

load_dotenv()
logger = get_logger(__name__)

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")]


def _normalize_symbol(symbol: str) -> str:
    """BTC/USDT → BTCUSDT"""
    return symbol.replace("/", "")


def run_sentiment_analysis(symbol: str) -> dict | None:
    """
    Chạy phân tích tâm lý cho một symbol.

    Returns:
        dict kết quả hoặc None nếu lỗi
    """
    norm_symbol = _normalize_symbol(symbol)
    try:
        headlines = fetch_news(norm_symbol)
        if not headlines:
            logger.warning(f"Không có tin tức cho {symbol}")
            return None

        sentiment = analyze_sentiment(norm_symbol, headlines)

        # Pack reason + outlooks into a single JSON string stored in `summary_reason`
        summary_payload = json.dumps({
            "reason":             sentiment.get("reason", ""),
            "short_term_outlook": sentiment.get("short_term_outlook", ""),
            "long_term_outlook":  sentiment.get("long_term_outlook", ""),
        }, ensure_ascii=False)

        result = {
            "symbol": norm_symbol,
            "sentiment_score": sentiment["score"],
            "summary_reason": summary_payload,
            "source_count": len(headlines),
        }
        return result
    except Exception as e:
        logger.error(f"Lỗi khi phân tích tâm lý {symbol}: {e}")
        return None


def save_to_db(result: dict) -> None:
    """Lưu kết quả vào bảng sentiment_scores trên Supabase."""
    client = get_client()
    payload = {
        "symbol": result["symbol"],
        "sentiment_score": result["sentiment_score"],
        "summary_reason": result["summary_reason"],
        "source_count": result["source_count"],
    }
    client.table("sentiment_scores").insert(payload).execute()
    logger.info(f"Đã lưu sentiment_score cho {result['symbol']}: {result['sentiment_score']:+d}")


def print_summary(results: list[dict]) -> None:
    """In bảng tóm tắt điểm tâm lý ra terminal."""
    print("\n" + "=" * 70)
    print("  BẢNG ĐIỂM TÂM LÝ (SENTIMENT ANALYSIS)")
    print("=" * 70)
    print(f"{'Symbol':<12} {'Điểm':>6} {'Tin':>5}  {'Lý do'}")
    print("-" * 70)
    for r in results:
        sentiment_label = "🟢 Tích cực" if r["sentiment_score"] >= 40 else (
            "🔴 Tiêu cực" if r["sentiment_score"] <= -40 else "⚪ Trung tính"
        )
        try:
            reason_text = json.loads(r["summary_reason"]).get("reason", "")
        except Exception:
            reason_text = r["summary_reason"]
        print(f"{r['symbol']:<12} {r['sentiment_score']:>+6} {r['source_count']:>5}  {reason_text[:45]}  {sentiment_label}")
    print("=" * 70 + "\n")


def main():
    logger.info(f"=== BẮT ĐẦU PHÂN TÍCH TÂM LÝ | Symbols: {SYMBOLS} ===")
    results = []

    for symbol in SYMBOLS:
        result = run_sentiment_analysis(symbol)
        if result:
            results.append(result)
            try:
                save_to_db(result)
            except Exception as e:
                logger.warning(f"Không lưu được DB cho {symbol}: {e}")

    if results:
        print_summary(results)
    else:
        logger.error("Không có kết quả tâm lý nào.")

    logger.info("=== PHÂN TÍCH TÂM LÝ HOÀN TẤT ===")


if __name__ == "__main__":
    main()
