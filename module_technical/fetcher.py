"""
module_technical/fetcher.py
---------------------------
Lấy dữ liệu nến OHLCV từ Binance thông qua thư viện ccxt.
Trả về DataFrame chuẩn hóa để indicators.py sử dụng.
"""

import os

import ccxt
import pandas as pd
from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

# Số nến tối thiểu để tính EMA 200
MIN_CANDLES = 250


def get_exchange() -> ccxt.binance:
    """Khởi tạo Binance exchange client (chỉ cần read-only, không cần API key)."""
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_SECRET_KEY", "")

    # Bỏ qua key nếu chưa được cấu hình thực (chứa "your_" là placeholder)
    use_auth = api_key and not api_key.startswith("your_")

    config = {
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
            # Tắt fetch currencies khi không dùng private endpoint
            "fetchMarkets": ["spot"],
        },
    }
    if use_auth:
        config["apiKey"] = api_key
        config["secret"] = secret

    exchange = ccxt.binance(config)
    return exchange


def fetch_ohlcv(symbol: str, timeframe: str = "4h", limit: int = MIN_CANDLES) -> pd.DataFrame:
    """
    Lấy dữ liệu OHLCV từ Binance.

    Args:
        symbol:    Cặp giao dịch, ví dụ 'BTC/USDT'
        timeframe: Khung thời gian, ví dụ '4h', '1h', '1d'
        limit:     Số lượng nến cần lấy (tối thiểu 250 để tính EMA200)

    Returns:
        DataFrame với cột: timestamp, open, high, low, close, volume
    """
    exchange = get_exchange()
    logger.info(f"Đang lấy {limit} nến {timeframe} cho {symbol} từ Binance...")

    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # Chuyển kiểu dữ liệu về float
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    logger.info(f"Lấy thành công {len(df)} nến. Giá đóng cửa cuối: {df['close'].iloc[-1]:.4f}")
    return df
