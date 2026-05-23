"""
module_confluence/scoring.py
------------------------------
Thuật toán tính điểm hợp nhất (Weighted Confluence Score).

Công thức:
    Final Score = (Technical Score × TECH_WEIGHT) + (Sentiment Score × SENTIMENT_WEIGHT)
    Mặc định:   Final Score = (Tech × 0.6) + (Sentiment × 0.4)

Logic ra lệnh:
    Final Score >= +THRESHOLD  →  BUY
    Final Score <= -THRESHOLD  →  SELL
    Còn lại                    →  HOLD
"""

import os

from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

TECH_WEIGHT = float(os.getenv("TECH_WEIGHT", "0.6"))
SENTIMENT_WEIGHT = float(os.getenv("SENTIMENT_WEIGHT", "0.4"))
SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "40"))


def calculate_final_score(tech_score: int, sentiment_score: int) -> float:
    """
    Tính điểm hợp nhất có trọng số.

    Args:
        tech_score:      Điểm kỹ thuật (-100 đến +100)
        sentiment_score: Điểm tâm lý (-100 đến +100)

    Returns:
        final_score: float
    """
    final = (tech_score * TECH_WEIGHT) + (sentiment_score * SENTIMENT_WEIGHT)
    return round(final, 2)


def determine_action(final_score: float) -> str:
    """
    Xác định hành động giao dịch từ điểm hợp nhất.

    Returns:
        'BUY', 'SELL', hoặc 'HOLD'
    """
    if final_score >= SIGNAL_THRESHOLD:
        return "BUY"
    elif final_score <= -SIGNAL_THRESHOLD:
        return "SELL"
    return "HOLD"


def estimate_win_rate(final_score: float, action: str) -> float:
    """
    Ước tính tỷ lệ thắng dựa trên độ mạnh của tín hiệu.
    Đây là ước lượng tuyến tính đơn giản, cần backtest thực tế để hiệu chỉnh.

    Returns:
        win_rate: float trong khoảng [0.50, 0.85]
    """
    if action == "HOLD":
        return 0.50

    abs_score = abs(final_score)
    # Ánh xạ: score=40 → 55%, score=100 → 85%
    win_rate = 0.50 + (abs_score - SIGNAL_THRESHOLD) / (100 - SIGNAL_THRESHOLD) * 0.35
    return round(min(win_rate, 0.85), 3)
