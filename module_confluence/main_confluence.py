"""
module_confluence/main_confluence.py
--------------------------------------
Điểm vào chính của Bộ Hợp nhất (Confluence Engine).
Đọc điểm kỹ thuật và tâm lý mới nhất từ Supabase,
tính điểm hợp nhất và lưu tín hiệu vào signals_history.

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_confluence.main_confluence
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from core_shared.database import get_client
from core_shared.logger import get_logger
from module_confluence.scoring import calculate_final_score, determine_action, estimate_win_rate

load_dotenv()
logger = get_logger(__name__)

SYMBOLS = [s.strip().replace("/", "") for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")]


def get_latest_tech_score(symbol: str) -> int | None:
    """Lấy điểm kỹ thuật mới nhất cho symbol từ Supabase."""
    client = get_client()
    response = (
        client.table("technical_scores")
        .select("tech_score")
        .eq("symbol", symbol)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["tech_score"]
    logger.warning(f"Không tìm thấy technical_score cho {symbol}")
    return None


def get_latest_sentiment_score(symbol: str) -> tuple[int, str] | tuple[None, None]:
    """Lấy điểm tâm lý mới nhất cho symbol từ Supabase."""
    client = get_client()
    response = (
        client.table("sentiment_scores")
        .select("sentiment_score, summary_reason")
        .eq("symbol", symbol)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["sentiment_score"], response.data[0].get("summary_reason", "")
    logger.warning(f"Không tìm thấy sentiment_score cho {symbol}")
    return None, None


def _is_duplicate_signal(symbol: str, action: str, lookback_hours: int = 4) -> bool:
    """
    Kiểm tra xem đã có tín hiệu cùng action trong N giờ gần đây chưa.
    Tránh spam kênh Telegram khi chạy cron job mỗi tiếng.
    """
    from datetime import datetime, timedelta, timezone
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    response = (
        client.table("signals_history")
        .select("id")
        .eq("symbol", symbol)
        .eq("action", action)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def save_signal(symbol: str, final_score: float, action: str, win_rate: float) -> None:
    """Lưu tín hiệu hợp nhất vào bảng signals_history."""
    from datetime import datetime, timedelta, timezone
    client = get_client()
    free_delay_h = int(os.getenv("FREE_DELAY_HOURS", "24"))
    free_send_after = (datetime.now(timezone.utc) + timedelta(hours=free_delay_h)).isoformat()
    payload = {
        "symbol": symbol,
        "final_score": final_score,
        "action": action,
        "win_rate_estimated": win_rate,
        "is_sent": False,
        "is_sent_vip": False,
        "is_sent_free": False,
        "free_send_after": free_send_after,
    }
    client.table("signals_history").insert(payload).execute()
    logger.info(f"Đã lưu tín hiệu {action} cho {symbol} | Score: {final_score:+.1f} | WinRate: {win_rate:.0%}")


def run_confluence(symbol: str) -> dict | None:
    """Chạy bộ hợp nhất cho một symbol."""
    tech_score = get_latest_tech_score(symbol)
    sentiment_score, sentiment_reason = get_latest_sentiment_score(symbol)

    if tech_score is None or sentiment_score is None:
        logger.warning(f"Thiếu dữ liệu cho {symbol}. Bỏ qua.")
        return None

    final_score = calculate_final_score(tech_score, sentiment_score)
    action = determine_action(final_score)
    win_rate = estimate_win_rate(final_score, action)

    result = {
        "symbol": symbol,
        "tech_score": tech_score,
        "sentiment_score": sentiment_score,
        "sentiment_reason": sentiment_reason,
        "final_score": final_score,
        "action": action,
        "win_rate": win_rate,
        "is_duplicate": False,
    }

    # Không lưu nếu cùng action đã tồn tại trong 4 giờ qua
    if action != "HOLD" and _is_duplicate_signal(symbol, action):
        logger.info(f"{symbol}: Tín hiệu {action} trùng với chu kỳ trước, bỏ qua lưu DB.")
        result["is_duplicate"] = True

    return result


def print_summary(results: list[dict]) -> None:
    """In bảng tín hiệu cuối cùng ra terminal."""
    print("\n" + "=" * 70)
    print("  TÍN HIỆU HỢP NHẤT (CONFLUENCE SIGNALS)")
    print("=" * 70)
    print(f"{'Symbol':<12} {'Tech':>6} {'Sent':>6} {'Final':>7} {'WinRate':>8}  {'Action'}")
    print("-" * 70)
    for r in results:
        action_icon = "🟢 BUY " if r["action"] == "BUY" else ("🔴 SELL" if r["action"] == "SELL" else "⚪ HOLD")
        print(
            f"{r['symbol']:<12} {r['tech_score']:>+6} {r['sentiment_score']:>+6} "
            f"{r['final_score']:>+7.1f} {r['win_rate']:>7.0%}  {action_icon}"
        )
        if r["sentiment_reason"]:
            try:
                import json as _json
                _ai = _json.loads(r["sentiment_reason"]).get("reason", r["sentiment_reason"])
            except Exception:
                _ai = r["sentiment_reason"]
            print(f"  └─ AI: {_ai[:60]}")
    print("=" * 70 + "\n")


def main():
    logger.info(f"=== BẮT ĐẦU CONFLUENCE ENGINE | Symbols: {SYMBOLS} ===")
    results = []

    for symbol in SYMBOLS:
        result = run_confluence(symbol)
        if result:
            results.append(result)
            if not result.get("is_duplicate"):
                try:
                    save_signal(symbol, result["final_score"], result["action"], result["win_rate"])
                except Exception as e:
                    logger.warning(f"Không lưu được tín hiệu cho {symbol}: {e}")

    if results:
        print_summary(results)
    else:
        logger.error("Không có tín hiệu nào được tạo. Chạy module_technical và module_sentiment trước.")

    logger.info("=== CONFLUENCE ENGINE HOÀN TẤT ===")


if __name__ == "__main__":
    main()
