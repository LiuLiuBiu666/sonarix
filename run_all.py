"""
run_all.py
-----------
Script điều phối — chạy toàn bộ pipeline một lần theo thứ tự:
    1. Technical Analysis
    2. Sentiment Analysis
    3. Confluence Engine
    4. Telegram Delivery

Dùng cho Cron Job hoặc PM2 schedule.

Cách chạy:
    cd crypto-hybrid-bot
    python run_all.py
"""

import os
import sys
import traceback
from datetime import datetime, timezone

# Force UTF-8 stdout/stderr so Vietnamese summary tables don't crash on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger("run_all")


def run_step(name: str, func) -> bool:
    """Chạy một bước trong pipeline, bắt lỗi và tiếp tục."""
    logger.info(f"▶ Bắt đầu: {name}")
    try:
        func()
        logger.info(f"✓ Hoàn thành: {name}")
        return True
    except Exception as e:
        logger.error(f"✗ Lỗi tại [{name}]: {e}")
        logger.debug(traceback.format_exc())
        return False


def main():
    start_time = datetime.now(timezone.utc)
    logger.info(f"{'='*50}")
    logger.info(f"PIPELINE BẮT ĐẦU — {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info(f"{'='*50}")

    # Import lazy để lỗi một module không ảnh hưởng module khác
    results = {}

    # Bước 1: Technical
    from module_technical.main_tech import main as tech_main
    results["Technical"] = run_step("Technical Analysis", tech_main)

    # Bước 2: Sentiment
    from module_sentiment.main_sentiment import main as sent_main
    results["Sentiment"] = run_step("Sentiment Analysis", sent_main)

    # Bước 3: Confluence (chỉ chạy nếu ít nhất 1 trong 2 bước trên OK)
    if results["Technical"] or results["Sentiment"]:
        from module_confluence.main_confluence import main as conf_main
        results["Confluence"] = run_step("Confluence Engine", conf_main)
    else:
        logger.warning("Bỏ qua Confluence do cả Technical lẫn Sentiment đều thất bại.")
        results["Confluence"] = False

    # Bước 4: Delivery (chỉ chạy nếu Confluence OK)
    if results["Confluence"]:
        from module_delivery.discord_bot import main as discord_main
        results["Discord"] = run_step("Discord Delivery", discord_main)
    else:
        logger.warning("Bỏ qua Delivery do Confluence thất bại.")
        results["Discord"] = False

    # Tóm tắt
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(f"{'='*50}")
    logger.info(f"KẾT QUẢ PIPELINE ({elapsed:.1f}s):")
    for step, ok in results.items():
        status = "✓ OK" if ok else "✗ FAIL"
        logger.info(f"  {status}  {step}")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    main()
