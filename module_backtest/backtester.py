"""
module_backtest/backtester.py
------------------------------
Engine backtest — mô phỏng tín hiệu giao dịch trên dữ liệu lịch sử.

Chiến lược:
  1. Lấy N nến lịch sử từ Binance (default 2000 nến = ~333 ngày × 4h)
  2. Tính toán toàn bộ chỉ báo trên full dataset (hiệu quả — không lặp từng window)
  3. Tại mỗi nến có tín hiệu BUY/SELL → ghi nhận giao dịch
  4. Exit sau HOLD_CANDLES nến (default 12 = 48h với 4h TF)
  5. Tính P&L từng trade, equity curve, các chỉ số hiệu suất

Giả định:
  - Vào lệnh tại giá Close của nến tín hiệu
  - Ra lệnh tại giá Close của nến exit
  - Không tính phí giao dịch (để hiệu chỉnh sau với fee thực)
  - Không dùng stop-loss (để đo thuần chất lượng tín hiệu)
"""

import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from core_shared.logger import get_logger
from module_technical.fetcher import fetch_ohlcv
from module_technical.indicators import (
    _BB_LOWER_COL,
    _BB_MID_COL,
    _BB_UPPER_COL,
    _EMA_COL,
    _MACD_COL,
    _MACD_SIG_COL,
    _RSI_COL,
    _VOL_MA_COL,
    calculate_tech_score,
)

load_dotenv()
logger = get_logger(__name__)

_SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "40"))
_DEFAULT_HOLD_CANDLES = 12   # 12 × 4h = 48 giờ
_DEFAULT_HISTORY_LIMIT = 2000  # ~333 ngày với 4h


def _determine_action(score: float) -> str:
    if score >= _SIGNAL_THRESHOLD:
        return "BUY"
    elif score <= -_SIGNAL_THRESHOLD:
        return "SELL"
    return "HOLD"


def _compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính tất cả chỉ báo trên toàn bộ DataFrame một lần duy nhất.
    Hiệu quả hơn nhiều so với gọi calculate_indicators() theo từng window.
    """
    import pandas_ta as ta  # noqa: F401 — kích hoạt accessor df.ta

    df = df.copy()
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=200, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2.0, append=True)
    df[_VOL_MA_COL] = df["volume"].rolling(window=20).mean()
    return df.dropna()  # Bỏ các dòng warmup (NaN do EMA200)


def _row_to_indicators(row: pd.Series, prev_row: pd.Series) -> dict:
    """Trích xuất dict indicators từ một hàng DataFrame đã tính chỉ báo."""
    return {
        "rsi":              float(row.get(_RSI_COL, 50)),
        "ema200":           float(row.get(_EMA_COL, 0)),
        "close":            float(row["close"]),
        "macd":             float(row.get(_MACD_COL, 0)),
        "macd_signal":      float(row.get(_MACD_SIG_COL, 0)),
        "macd_prev":        float(prev_row.get(_MACD_COL, 0)),
        "macd_signal_prev": float(prev_row.get(_MACD_SIG_COL, 0)),
        "bb_lower":         float(row.get(_BB_LOWER_COL, 0)),
        "bb_upper":         float(row.get(_BB_UPPER_COL, 0)),
        "bb_mid":           float(row.get(_BB_MID_COL, 0)),
        "volume":           float(row["volume"]),
        "vol_ma20":         float(row.get(_VOL_MA_COL, 0)),
    }


def run_backtest(
    symbol: str,
    timeframe: str = "4h",
    history_limit: int = _DEFAULT_HISTORY_LIMIT,
    hold_candles: int = _DEFAULT_HOLD_CANDLES,
) -> list[dict]:
    """
    Chạy backtest cho một symbol trên dữ liệu lịch sử.

    Args:
        symbol:        Cặp giao dịch, ví dụ 'BTC/USDT'
        timeframe:     Khung thời gian
        history_limit: Số nến lịch sử cần lấy
        hold_candles:  Số nến giữ lệnh trước khi thoát

    Returns:
        Danh sách dict mỗi trade: timestamp, action, entry_price,
        exit_price, pnl_pct, score
    """
    logger.info(f"Backtest {symbol} | TF:{timeframe} | {history_limit} nến | Hold:{hold_candles} nến")

    # 1. Lấy dữ liệu lịch sử
    df_raw = fetch_ohlcv(symbol, timeframe, limit=history_limit)

    # 2. Tính tất cả chỉ báo một lần
    df = _compute_all_indicators(df_raw)
    logger.info(f"Dữ liệu sau warmup: {len(df)} nến (từ {df.index[0]} đến {df.index[-1]})")

    trades = []

    # 3. Duyệt từng nến (bỏ nến cuối cùng vì không có exit)
    for i in range(1, len(df) - hold_candles):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        indicators = _row_to_indicators(row, prev_row)
        score, _ = calculate_tech_score(indicators)
        action = _determine_action(score)

        if action not in ("BUY", "SELL"):
            continue

        entry_price = float(row["close"])
        exit_row = df.iloc[i + hold_candles]
        exit_price = float(exit_row["close"])

        # Tính P&L theo hướng giao dịch
        if action == "BUY":
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:  # SELL / SHORT
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        trades.append({
            "timestamp":   str(df.index[i]),
            "action":      action,
            "entry_price": round(entry_price, 4),
            "exit_price":  round(exit_price, 4),
            "pnl_pct":     round(pnl_pct, 3),
            "score":       score,
        })

    logger.info(f"Backtest {symbol}: {len(trades)} giao dịch được tìm thấy")
    return trades
