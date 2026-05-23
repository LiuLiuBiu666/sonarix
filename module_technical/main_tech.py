"""
module_technical/main_tech.py
------------------------------
Điểm vào chính của luồng phân tích kỹ thuật (Phase 2: Multi-Timeframe).

Chiến lược MTF:
  - Chạy song song Primary TF (4h) + Secondary TF (1h)
  - Cả hai đồng thuận BUY/SELL  → CONFIRMED, cộng MTF_BONUS (+15)
  - Hai TF trái chiều           → CONFLICT, trừ MTF_PENALTY (-20) → thường thành HOLD
  - Chỉ có Primary TF           → dùng kết quả Primary TF thuần

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_technical.main_tech
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from core_shared.database import get_client
from core_shared.logger import get_logger
from module_technical.fetcher import fetch_ohlcv
from module_technical.indicators import calculate_indicators, calculate_tech_score

load_dotenv()
logger = get_logger(__name__)

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
SECONDARY_TIMEFRAME = os.getenv("SECONDARY_TIMEFRAME", "1h")
MTF_ENABLED = os.getenv("MTF_ENABLED", "true").lower() == "true"

# MTF score adjustment
_MTF_BONUS = 15     # cộng khi 2 TF đồng thuận
_MTF_PENALTY = 20   # trừ khi 2 TF xung đột
_SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "40"))


def _determine_action(score: float) -> str:
    if score >= _SIGNAL_THRESHOLD:
        return "BUY"
    elif score <= -_SIGNAL_THRESHOLD:
        return "SELL"
    return "HOLD"


def _analyze_single_timeframe(symbol: str, timeframe: str) -> dict | None:
    """Chạy phân tích kỹ thuật đầy đủ cho một TF cụ thể."""
    try:
        df = fetch_ohlcv(symbol, timeframe)
        indicators = calculate_indicators(df)
        score, breakdown = calculate_tech_score(indicators)
        return {
            "timeframe": timeframe,
            "score": score,
            "action": _determine_action(score),
            "indicators": indicators,
            "breakdown": breakdown,
        }
    except Exception as e:
        logger.warning(f"Không lấy được dữ liệu {symbol} {timeframe}: {e}")
        return None


def run_technical_analysis(symbol: str) -> dict | None:
    """
    Chạy phân tích kỹ thuật Multi-Timeframe cho một symbol.

    Returns:
        dict kết quả tổng hợp hoặc None nếu lỗi hoàn toàn
    """
    symbol_norm = symbol.replace("/", "")
    logger.info(f"Phân tích MTF {symbol_norm} | Primary:{TIMEFRAME} Secondary:{SECONDARY_TIMEFRAME}")

    # Chạy song song 2 TF để tiết kiệm thời gian
    primary_result = None
    secondary_result = None

    if MTF_ENABLED:
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_primary = executor.submit(_analyze_single_timeframe, symbol, TIMEFRAME)
            fut_secondary = executor.submit(_analyze_single_timeframe, symbol, SECONDARY_TIMEFRAME)
            primary_result = fut_primary.result()
            secondary_result = fut_secondary.result()
    else:
        primary_result = _analyze_single_timeframe(symbol, TIMEFRAME)

    if primary_result is None:
        logger.error(f"Không có dữ liệu Primary TF cho {symbol}")
        return None

    final_score = primary_result["score"]
    mtf_status = "DISABLED"
    mtf_detail = ""

    # ── Multi-Timeframe Confluence ───────────────────────────────
    if MTF_ENABLED and secondary_result is not None:
        p_action = primary_result["action"]
        s_action = secondary_result["action"]

        if p_action != "HOLD" and p_action == s_action:
            # Đồng thuận: cộng bonus, giữ hướng
            final_score += _MTF_BONUS if final_score > 0 else -_MTF_BONUS
            final_score = max(-100, min(100, final_score))
            mtf_status = "CONFIRMED"
            mtf_detail = f"{TIMEFRAME}({p_action}) ✦ {SECONDARY_TIMEFRAME}({s_action}) — Đồng thuận +{_MTF_BONUS}"
            logger.info(f"{symbol_norm}: MTF CONFIRMED — {mtf_detail}")
        elif p_action != "HOLD" and s_action != "HOLD" and p_action != s_action:
            # Xung đột: trừ penalty
            final_score = final_score - _MTF_PENALTY if final_score > 0 else final_score + _MTF_PENALTY
            mtf_status = "CONFLICT"
            mtf_detail = f"{TIMEFRAME}({p_action}) ≠ {SECONDARY_TIMEFRAME}({s_action}) — Xung đột -{_MTF_PENALTY}"
            logger.warning(f"{symbol_norm}: MTF CONFLICT — {mtf_detail}")
        else:
            mtf_status = "NEUTRAL"
            mtf_detail = f"{TIMEFRAME}({p_action}) | {SECONDARY_TIMEFRAME}({s_action or 'N/A'}) — Trung tính"

    final_action = _determine_action(final_score)
    indicators = primary_result["indicators"]

    result = {
        "symbol": symbol_norm,
        "timeframe": TIMEFRAME,
        "tech_score": final_score,
        "indicators_data": {
            "rsi":     indicators["rsi"],
            "ema200":  indicators["ema200"],
            "close":   indicators["close"],
            "macd":    indicators["macd"],
            "bb_lower": indicators.get("bb_lower", 0),
            "bb_upper": indicators.get("bb_upper", 0),
            "volume_ratio": round(
                indicators["volume"] / indicators["vol_ma20"], 2
            ) if indicators.get("vol_ma20", 0) > 0 else None,
            "breakdown": primary_result["breakdown"],
            "mtf": {
                "status": mtf_status,
                "detail": mtf_detail,
                "primary_score": primary_result["score"],
                "secondary_score": secondary_result["score"] if secondary_result else None,
                "secondary_action": secondary_result["action"] if secondary_result else None,
            },
        },
        "action": final_action,
    }
    return result


def save_to_db(result: dict) -> None:
    """Lưu kết quả phân tích vào bảng technical_scores trên Supabase."""
    client = get_client()
    payload = {
        "symbol":          result["symbol"],
        "timeframe":       result["timeframe"],
        "tech_score":      result["tech_score"],
        "indicators_data": result["indicators_data"],
    }
    client.table("technical_scores").insert(payload).execute()
    logger.info(f"Đã lưu technical_score {result['symbol']}: {result['tech_score']:+d} [{result['action']}]")


def print_summary(results: list[dict]) -> None:
    """In bảng tóm tắt điểm kỹ thuật ra terminal."""
    mtf_label = f" (MTF: {TIMEFRAME}+{SECONDARY_TIMEFRAME})" if MTF_ENABLED else ""
    print("\n" + "=" * 78)
    print(f"  BẢNG ĐIỂM KỸ THUẬT{mtf_label}")
    print("=" * 78)
    print(f"{'Symbol':<12} {'Điểm':>6} {'RSI':>6} {'Vol×':>5} {'BB':>6} {'MTF':>10}  {'Action'}")
    print("-" * 78)
    for r in results:
        ind = r["indicators_data"]
        bd = ind["breakdown"]
        vol_str = f"{ind['volume_ratio']:.1f}x" if ind.get("volume_ratio") else "N/A"
        bb_score = bd.get("bollinger", {}).get("score", 0)
        bb_str = f"{bb_score:+d}" if bb_score != 0 else "—"
        mtf = ind.get("mtf", {})
        mtf_str = mtf.get("status", "—")[:9]
        action = r["action"]
        icon = "🟢 BUY" if action == "BUY" else ("🔴 SELL" if action == "SELL" else "⚪ HOLD")
        print(
            f"{r['symbol']:<12} {r['tech_score']:>+6} {ind['rsi']:>6.1f} "
            f"{vol_str:>5} {bb_str:>6} {mtf_str:>10}  {icon}"
        )
        if mtf.get("detail"):
            print(f"  └─ {mtf['detail']}")
    print("=" * 78 + "\n")


def main():
    logger.info(f"=== PHÂN TÍCH KỸ THUẬT MTF | Symbols: {SYMBOLS} | TF: {TIMEFRAME}+{SECONDARY_TIMEFRAME} ===")
    results = []

    for symbol in SYMBOLS:
        result = run_technical_analysis(symbol)
        if result:
            results.append(result)
            try:
                save_to_db(result)
            except Exception as e:
                logger.warning(f"Không lưu được DB cho {symbol}: {e}")

    if results:
        print_summary(results)
    else:
        logger.error("Không có kết quả nào. Kiểm tra kết nối Binance API.")

    logger.info("=== PHÂN TÍCH KỸ THUẬT HOÀN TẤT ===")


if __name__ == "__main__":
    main()


# ── Dead duplicate removed ───────────────────────────────────────────────────
# (single-TF phase-1 implementation that was shadowing the MTF version above)
