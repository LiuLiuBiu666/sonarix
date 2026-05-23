"""
module_backtest/main_backtest.py
---------------------------------
Điểm vào chính của luồng backtest — chạy cho tất cả SYMBOLS.

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_backtest.main_backtest

    # Chạy với tham số tùy chỉnh:
    SYMBOLS=BTC/USDT,ETH/USDT TIMEFRAME=4h HOLD_CANDLES=12 python -m module_backtest.main_backtest
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from core_shared.database import get_client
from core_shared.logger import get_logger
from module_backtest.backtester import run_backtest
from module_backtest.report import calculate_report, print_report

load_dotenv()
logger = get_logger(__name__)

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
HOLD_CANDLES = int(os.getenv("HOLD_CANDLES", "12"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "2000"))
SAVE_TO_DB = os.getenv("BACKTEST_SAVE_DB", "false").lower() == "true"


def save_report_to_db(report: dict) -> None:
    """Lưu báo cáo backtest vào Supabase (tuỳ chọn, cần bảng backtest_results)."""
    if report.get("total_trades", 0) == 0:
        return
    try:
        client = get_client()
        payload = {
            "symbol":           report["symbol"],
            "timeframe":        TIMEFRAME,
            "hold_candles":     HOLD_CANDLES,
            "history_limit":    HISTORY_LIMIT,
            "total_trades":     report["total_trades"],
            "win_rate":         report["win_rate"],
            "avg_win_pct":      report["avg_win_pct"],
            "avg_loss_pct":     report["avg_loss_pct"],
            "profit_factor":    min(report["profit_factor"], 9999.0),  # tránh inf
            "total_pnl_pct":    report["total_pnl_pct"],
            "expectancy_pct":   report["expectancy_pct"],
            "sharpe_ratio":     report["sharpe_ratio"],
            "max_drawdown_pct": report["max_drawdown_pct"],
        }
        client.table("backtest_results").insert(payload).execute()
        logger.info(f"Đã lưu backtest_results cho {report['symbol']}")
    except Exception as e:
        logger.warning(f"Không lưu được DB: {e}. Tiếp tục mà không lưu.")


def main():
    print("\n" + "=" * 70)
    print(f"  BACKTEST ENGINE — TF:{TIMEFRAME} | Hold:{HOLD_CANDLES} nến | Lịch sử:{HISTORY_LIMIT} nến")
    print("=" * 70)
    logger.info(f"Bắt đầu backtest | Symbols:{SYMBOLS} | TF:{TIMEFRAME} | Hold:{HOLD_CANDLES}")

    all_reports = []

    for symbol in SYMBOLS:
        try:
            trades = run_backtest(
                symbol=symbol,
                timeframe=TIMEFRAME,
                history_limit=HISTORY_LIMIT,
                hold_candles=HOLD_CANDLES,
            )
            report = calculate_report(symbol.replace("/", ""), trades)
            print_report(report)

            if SAVE_TO_DB:
                save_report_to_db(report)

            all_reports.append(report)

        except Exception as e:
            logger.error(f"Lỗi khi backtest {symbol}: {e}", exc_info=True)
            print(f"\n[LỖI] {symbol}: {e}")

    # In bảng so sánh tổng hợp
    valid_reports = [r for r in all_reports if r.get("total_trades", 0) > 0]
    if len(valid_reports) > 1:
        print("\n" + "=" * 70)
        print("  BẢNG SO SÁNH HIỆU SUẤT")
        print("=" * 70)
        print(f"{'Symbol':<12} {'Trades':>6} {'WinRate':>8} {'PF':>6} {'TotalPnL':>9} {'Sharpe':>7} {'MaxDD':>7}")
        print("-" * 70)
        for r in valid_reports:
            print(
                f"{r['symbol']:<12} {r['total_trades']:>6} "
                f"{r['win_rate']*100:>7.1f}% {r['profit_factor']:>6.2f} "
                f"{r['total_pnl_pct']:>+8.2f}% {r['sharpe_ratio']:>7.3f} "
                f"{r['max_drawdown_pct']:>6.2f}%"
            )
        print("=" * 70)

    logger.info("=== BACKTEST HOÀN TẤT ===")


if __name__ == "__main__":
    main()
