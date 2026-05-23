"""
module_backtest/report.py
--------------------------
Tính toán và in báo cáo hiệu suất backtest.

Các chỉ số:
  - Win Rate          : % giao dịch có lợi nhuận dương
  - Avg Win / Avg Loss: P&L trung bình khi thắng / thua
  - Profit Factor     : |tổng lợi nhuận| / |tổng thua lỗ|
  - Total PnL %       : Tổng lợi nhuận cộng dồn (non-compounding)
  - Sharpe Ratio      : mean(PnL) / std(PnL) — đo risk-adjusted return
  - Max Drawdown %    : Mức sụt vốn tối đa từ đỉnh (equity curve)
  - Expectancy        : Lợi nhuận kỳ vọng trên mỗi giao dịch
"""

import statistics
from typing import Any


def calculate_report(symbol: str, trades: list[dict]) -> dict[str, Any]:
    """
    Tính toán tất cả chỉ số hiệu suất từ danh sách trades.

    Args:
        symbol: Mã coin (để hiển thị)
        trades: Danh sách dict từ backtester.run_backtest()

    Returns:
        dict chứa tất cả chỉ số hiệu suất
    """
    if not trades:
        return {
            "symbol": symbol,
            "total_trades": 0,
            "note": "Không có tín hiệu nào trong khoảng thời gian backtest",
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_trades = len(pnls)
    win_rate = len(wins) / total_trades

    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0

    total_win = sum(wins)
    total_loss = sum(losses)
    profit_factor = abs(total_win / total_loss) if total_loss != 0 else float("inf")

    total_pnl = sum(pnls)

    # Expectancy per trade
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # Sharpe Ratio (simplified — dùng per-trade return)
    if total_trades > 1:
        mean_ret = statistics.mean(pnls)
        std_ret = statistics.stdev(pnls)
        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    # Max Drawdown (equity curve, bắt đầu từ 100 đơn vị)
    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    equity_curve = [equity]

    for pnl in pnls:
        equity *= (1 + pnl / 100)
        equity_curve.append(round(equity, 4))
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_drawdown = max(max_drawdown, dd)

    # Thống kê theo hướng giao dịch
    buy_trades = [t for t in trades if t["action"] == "BUY"]
    sell_trades = [t for t in trades if t["action"] == "SELL"]
    buy_wr = len([t for t in buy_trades if t["pnl_pct"] > 0]) / len(buy_trades) if buy_trades else 0
    sell_wr = len([t for t in sell_trades if t["pnl_pct"] > 0]) / len(sell_trades) if sell_trades else 0

    return {
        "symbol":           symbol,
        "total_trades":     total_trades,
        "buy_trades":       len(buy_trades),
        "sell_trades":      len(sell_trades),
        "win_rate":         round(win_rate, 4),
        "buy_win_rate":     round(buy_wr, 4),
        "sell_win_rate":    round(sell_wr, 4),
        "avg_win_pct":      round(avg_win, 3),
        "avg_loss_pct":     round(avg_loss, 3),
        "profit_factor":    round(profit_factor, 3),
        "total_pnl_pct":    round(total_pnl, 3),
        "final_equity":     round(equity_curve[-1], 2),
        "expectancy_pct":   round(expectancy, 3),
        "sharpe_ratio":     round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown, 3),
        "equity_curve":     equity_curve,
    }


def print_report(report: dict) -> None:
    """In báo cáo backtest ra terminal theo định dạng đẹp."""
    if report.get("total_trades", 0) == 0:
        print(f"\n[{report['symbol']}] {report.get('note', 'Không có dữ liệu')}")
        return

    total = report["total_trades"]
    wr = report["win_rate"] * 100
    pf = report["profit_factor"]
    sharpe = report["sharpe_ratio"]

    # Đánh giá tổng quan
    if wr >= 55 and pf >= 1.5 and sharpe >= 0.3:
        rating = "⭐⭐⭐ XUẤT SẮC"
    elif wr >= 50 and pf >= 1.2:
        rating = "⭐⭐   TỐT"
    elif wr >= 45 and pf >= 1.0:
        rating = "⭐    TRUNG BÌNH"
    else:
        rating = "⚠️    CẦN CẢI THIỆN"

    print("\n" + "═" * 60)
    print(f"  BACKTEST REPORT — {report['symbol']}  {rating}")
    print("═" * 60)
    print(f"  Tổng giao dịch  : {total:>6}  (BUY: {report['buy_trades']} | SELL: {report['sell_trades']})")
    print(f"  Win Rate        : {wr:>6.1f}%  (BUY: {report['buy_win_rate']*100:.1f}% | SELL: {report['sell_win_rate']*100:.1f}%)")
    print(f"  Avg Win/Loss    : {report['avg_win_pct']:>+6.2f}% / {report['avg_loss_pct']:>+6.2f}%")
    print(f"  Profit Factor   : {pf:>6.3f}  (>1.5 tốt, >2.0 xuất sắc)")
    print(f"  Expectancy/Trade: {report['expectancy_pct']:>+6.3f}%")
    print("─" * 60)
    print(f"  Tổng PnL        : {report['total_pnl_pct']:>+6.2f}%  (non-compounding)")
    print(f"  Vốn cuối (100→) : {report['final_equity']:>7.2f}  (compounding)")
    print(f"  Max Drawdown    : {report['max_drawdown_pct']:>6.2f}%  (mức sụt vốn tệ nhất)")
    print(f"  Sharpe Ratio    : {sharpe:>6.3f}  (>0.5 tốt, >1.0 rất tốt)")
    print("═" * 60)
