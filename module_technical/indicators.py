"""
module_technical/indicators.py
-------------------------------
Tính toán chỉ báo kỹ thuật và chấm điểm theo thang -100 đến +100.

Bảng điểm (Phase 2 — đã cập nhật):
  RSI < 30              → +30 (quá bán)
  RSI > 70              → -30 (quá mua)
  30 ≤ RSI ≤ 70         →   0

  Giá > EMA200          → +40 (xu hướng tăng dài hạn)
  Giá < EMA200          → -40 (xu hướng giảm dài hạn)

  MACD cắt lên Signal   → +30 (động lượng dương)
  MACD cắt xuống Signal → -30 (động lượng âm)
  Không cắt             →   0

  [MỚI] Giá ≤ BB Lower  → +20 (oversold, mean-reversion tiềm năng)
  [MỚI] Giá ≥ BB Upper  → -20 (overbought, mean-reversion tiềm năng)
  [MỚI] Trong BB        →   0

  [MỚI] Volume > MA20×1.5 & có MACD crossover → MACD score ×1.2 (volume confirmation)

  Tổng: clamp [-100, +100]
"""

import pandas as pd
import pandas_ta as ta

from core_shared.logger import get_logger

logger = get_logger(__name__)

# Tên cột pandas_ta
_RSI_COL = "RSI_14"
_EMA_COL = "EMA_200"
_MACD_COL = "MACD_12_26_9"
_MACD_SIG_COL = "MACDs_12_26_9"
_BB_LOWER_COL = "BBL_20_2.0_2.0"
_BB_UPPER_COL = "BBU_20_2.0_2.0"
_BB_MID_COL   = "BBM_20_2.0_2.0"
_VOL_MA_COL = "VOL_MA20"


def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Tính RSI, EMA200, MACD, Bollinger Bands và Volume MA20 từ DataFrame OHLCV.

    Args:
        df: DataFrame với cột open/high/low/close/volume (index là timestamp)

    Returns:
        dict chứa các giá trị chỉ báo mới nhất của nến cuối cùng
    """
    df = df.copy()

    # RSI (14)
    df.ta.rsi(length=14, append=True)

    # EMA 200
    df.ta.ema(length=200, append=True)

    # MACD (12, 26, 9)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)

    # Bollinger Bands (20, stddev=2.0)
    df.ta.bbands(length=20, std=2.0, append=True)

    # Volume MA20 (tính thủ công để đảm bảo tên cột ổn định)
    df[_VOL_MA_COL] = df["volume"].rolling(window=20).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    indicators = {
        "rsi":              round(float(last.get(_RSI_COL, 50)), 2),
        "ema200":           round(float(last.get(_EMA_COL, 0)), 4),
        "close":            round(float(last["close"]), 4),
        "macd":             round(float(last.get(_MACD_COL, 0)), 6),
        "macd_signal":      round(float(last.get(_MACD_SIG_COL, 0)), 6),
        "macd_prev":        round(float(prev.get(_MACD_COL, 0)), 6),
        "macd_signal_prev": round(float(prev.get(_MACD_SIG_COL, 0)), 6),
        "bb_lower":         round(float(last.get(_BB_LOWER_COL, 0)), 4),
        "bb_upper":         round(float(last.get(_BB_UPPER_COL, 0)), 4),
        "bb_mid":           round(float(last.get(_BB_MID_COL, 0)), 4),
        "volume":           round(float(last["volume"]), 2),
        "vol_ma20":         round(float(last.get(_VOL_MA_COL, 0)), 2),
    }
    return indicators


def calculate_tech_score(indicators: dict) -> tuple[int, dict]:
    """
    Chấm điểm kỹ thuật từ các chỉ báo đã tính (Phase 2: thêm BB + Volume).

    Args:
        indicators: dict từ calculate_indicators()

    Returns:
        Tuple (tech_score: int trong [-100,+100], breakdown: dict)
    """
    score = 0
    breakdown = {}

    # ── RSI Score ──────────────────────────────────────────────────
    rsi = indicators["rsi"]
    if rsi < 30:
        rsi_score = 30
        rsi_reason = f"RSI={rsi:.1f} — Quá bán (Oversold)"
    elif rsi > 70:
        rsi_score = -30
        rsi_reason = f"RSI={rsi:.1f} — Quá mua (Overbought)"
    else:
        rsi_score = 0
        rsi_reason = f"RSI={rsi:.1f} — Trung tính"
    score += rsi_score
    breakdown["rsi"] = {"score": rsi_score, "reason": rsi_reason}

    # ── EMA200 Score ───────────────────────────────────────────────
    close = indicators["close"]
    ema200 = indicators["ema200"]
    if ema200 > 0:
        if close > ema200:
            ema_score = 40
            ema_reason = f"Giá ({close:.4f}) > EMA200 ({ema200:.4f}) — Xu hướng TĂNG"
        else:
            ema_score = -40
            ema_reason = f"Giá ({close:.4f}) < EMA200 ({ema200:.4f}) — Xu hướng GIẢM"
        score += ema_score
        breakdown["ema200"] = {"score": ema_score, "reason": ema_reason}

    # ── MACD Crossover Score (với Volume Confirmation) ─────────────
    macd = indicators["macd"]
    macd_signal = indicators["macd_signal"]
    macd_prev = indicators["macd_prev"]
    macd_signal_prev = indicators["macd_signal_prev"]
    volume = indicators["volume"]
    vol_ma20 = indicators["vol_ma20"]

    macd_crossed_up = macd_prev < macd_signal_prev and macd > macd_signal
    macd_crossed_down = macd_prev > macd_signal_prev and macd < macd_signal

    # Volume confirmation: tăng trọng số MACD 20% khi volume cao bất thường
    vol_confirmed = vol_ma20 > 0 and volume > vol_ma20 * 1.5
    vol_multiplier = 1.2 if vol_confirmed else 1.0

    if macd_crossed_up:
        raw_score = 30
        macd_reason = "MACD cắt lên Signal — Động lượng DƯƠNG"
        if vol_confirmed:
            macd_reason += f" ✦ Volume cao ({volume/vol_ma20:.1f}x MA20) — XÁC NHẬN MẠNH"
    elif macd_crossed_down:
        raw_score = -30
        macd_reason = "MACD cắt xuống Signal — Động lượng ÂM"
        if vol_confirmed:
            macd_reason += f" ✦ Volume cao ({volume/vol_ma20:.1f}x MA20) — XÁC NHẬN MẠNH"
    else:
        raw_score = 0
        macd_reason = f"MACD={macd:.6f} vs Signal={macd_signal:.6f} — Chưa có crossover"

    macd_score = int(raw_score * vol_multiplier)
    score += macd_score
    breakdown["macd"] = {
        "score": macd_score,
        "reason": macd_reason,
        "volume_confirmed": vol_confirmed,
    }

    # ── Bollinger Bands Score ──────────────────────────────────────
    bb_lower = indicators["bb_lower"]
    bb_upper = indicators["bb_upper"]

    if bb_lower > 0 and bb_upper > 0:
        if close <= bb_lower:
            bb_score = 20
            bb_reason = f"Giá ({close:.4f}) ≤ BB Lower ({bb_lower:.4f}) — Oversold cực đoan"
        elif close >= bb_upper:
            bb_score = -20
            bb_reason = f"Giá ({close:.4f}) ≥ BB Upper ({bb_upper:.4f}) — Overbought cực đoan"
        else:
            bb_score = 0
            bb_mid = indicators["bb_mid"]
            bb_reason = f"Giá trong Bollinger Bands [{bb_lower:.4f} — {bb_upper:.4f}]"
        score += bb_score
        breakdown["bollinger"] = {"score": bb_score, "reason": bb_reason}

    # ── Clamp tổng điểm về [-100, +100] ───────────────────────────
    score = max(-100, min(100, score))

    logger.info(
        f"Điểm kỹ thuật: {score:+d} | "
        f"RSI:{rsi_score:+d} EMA:{breakdown.get('ema200',{}).get('score',0):+d} "
        f"MACD:{macd_score:+d} BB:{breakdown.get('bollinger',{}).get('score',0):+d}"
        + (" [VOL✦]" if vol_confirmed else "")
    )
    return score, breakdown


