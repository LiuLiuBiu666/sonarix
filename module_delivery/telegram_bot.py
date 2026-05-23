"""
module_delivery/telegram_bot.py
---------------------------------
Gửi tín hiệu BUY/SELL lên Telegram theo mô hình Free/VIP:

  VIP Channel  : Nhận tín hiệu NGAY LẬP TỨC (full info + AI reason)
  Free Channel : Nhận tín hiệu TRỄ N GIỜ (stripped info, CTA upgrade)

Nếu chỉ cấu hình TELEGRAM_CHANNEL_ID (không có VIP/Free riêng):
  → Gửi lên kênh duy nhất đó như Phase 1 (backward compat).

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_delivery.telegram_bot
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from core_shared.database import get_client
from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
_VIP_CHANNEL    = os.getenv("TELEGRAM_VIP_CHANNEL_ID", os.getenv("TELEGRAM_CHANNEL_ID", ""))
_FREE_CHANNEL   = os.getenv("TELEGRAM_FREE_CHANNEL_ID", "")
_FREE_DELAY_H   = int(os.getenv("FREE_DELAY_HOURS", "24"))
_SPLIT_ENABLED  = bool(_VIP_CHANNEL and _FREE_CHANNEL)


# ─────────────────────────────────────────────────────────────
# Định dạng tin nhắn
# ─────────────────────────────────────────────────────────────

_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def _escape_md(text: str) -> str:
    """Escape tất cả ký tự đặc biệt theo chuẩn Telegram MarkdownV2."""
    for ch in _MD_SPECIAL:
        text = text.replace(ch, f"\\{ch}")
    return text


def _score_bar(score: float, max_score: float = 100.0) -> str:
    pct = min(abs(score) / max_score, 1.0)
    filled = int(pct * 10)
    return "▓" * filled + "░" * (10 - filled)


def _fmt_vip_message(signal: dict) -> str:
    """Tin nhắn đầy đủ dành cho thành viên VIP."""
    action = signal["action"]
    icon   = "🟢" if action == "BUY" else "🔴"
    label  = "MUA (LONG)" if action == "BUY" else "BÁN (SHORT)"
    emoji  = "🚀" if action == "BUY" else "⚠️"

    score_bar = _score_bar(signal["final_score"])
    win_pct   = f"{signal['win_rate_estimated'] * 100:.0f}%" if signal.get("win_rate_estimated") else "N/A"
    timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC | %d/%m/%Y")
    tech_info = f"`{signal.get('tech_score', 'N/A'):+}`" if signal.get("tech_score") is not None else "`N/A`"
    sent_info = f"`{signal.get('sentiment_score', 'N/A'):+}`" if signal.get("sentiment_score") is not None else "`N/A`"
    reason    = signal.get("summary_reason", "")

    msg = (
        f"{icon} *\\[VIP\\]* {emoji} *{_escape_md(signal['symbol'])}* \\— {label}\n"
        f"{'─' * 30}\n"
        f"📊 *Điểm hợp nhất:* `{signal['final_score']:+.1f}` {score_bar}\n"
        f"📈 *Kỹ thuật:* {tech_info}   🧠 *Tâm lý:* {sent_info}\n"
        f"🎯 *Tỷ lệ thắng ước tính:* `{win_pct}`\n"
    )
    if reason:
        msg += f"💬 *AI nhận định:* _{_escape_md(reason)}_\n"
    msg += (
        f"{'─' * 30}\n"
        f"🕐 _{timestamp}_\n"
        f"⚡ _\\#CryptoHybridBot \\#VIP_"
    )
    return msg


def _fmt_free_message(signal: dict) -> str:
    """Tin nhắn rút gọn dành cho kênh Free (đã trễ N giờ)."""
    action = signal["action"]
    icon   = "🟢" if action == "BUY" else "🔴"
    label  = "MUA" if action == "BUY" else "BÁN"
    timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC | %d/%m/%Y")

    msg = (
        f"{icon} *{_escape_md(signal['symbol'])}* \\— {label}\n"
        f"{'─' * 30}\n"
        f"⏰ _Tín hiệu này đã gửi cho VIP {_FREE_DELAY_H} giờ trước_\n\n"
        f"💎 *Nâng cấp VIP* để nhận tín hiệu real\\-time \\+ AI phân tích đầy đủ\\!\n"
        f"{'─' * 30}\n"
        f"🕐 _{timestamp}_\n"
        f"⚡ _\\#CryptoHybridBot \\#Free_"
    )
    return msg


# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────

def _enrich_signal(signal: dict) -> dict:
    """Bổ sung tech_score và sentiment_score vào signal dict."""
    client = get_client()
    symbol = signal["symbol"]
    tech = client.table("technical_scores").select("tech_score").eq("symbol", symbol).order("created_at", desc=True).limit(1).execute()
    sent = client.table("sentiment_scores").select("sentiment_score, summary_reason").eq("symbol", symbol).order("created_at", desc=True).limit(1).execute()
    if tech.data:
        signal["tech_score"] = tech.data[0]["tech_score"]
    if sent.data:
        signal["sentiment_score"] = sent.data[0]["sentiment_score"]
        signal["summary_reason"]  = sent.data[0].get("summary_reason", "")
    return signal


def _mark_vip_sent(signal_id: int) -> None:
    client = get_client()
    client.table("signals_history").update({"is_sent_vip": True, "is_sent": True}).eq("id", signal_id).execute()


def _mark_free_sent(signal_id: int) -> None:
    client = get_client()
    # is_sent=TRUE hanya ketika kedua channel sudah terkirim
    client.table("signals_history").update({"is_sent_free": True}).eq("id", signal_id).execute()


def _mark_sent_legacy(signal_id: int) -> None:
    """Backward compat: single channel mode."""
    client = get_client()
    client.table("signals_history").update({"is_sent": True, "is_sent_vip": True, "is_sent_free": True}).eq("id", signal_id).execute()


def _get_vip_pending() -> list[dict]:
    client = get_client()
    resp = client.table("signals_history").select("*").eq("is_sent_vip", False).in_("action", ["BUY", "SELL"]).order("created_at", desc=False).execute()
    return resp.data or []


def _get_free_pending() -> list[dict]:
    """Lấy tín hiệu Free đến hạn gửi (free_send_after <= NOW())."""
    from datetime import timezone
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = (
        client.table("signals_history")
        .select("*")
        .eq("is_sent_free", False)
        .in_("action", ["BUY", "SELL"])
        .lte("free_send_after", now_iso)
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []


def _get_legacy_pending() -> list[dict]:
    """Backward compat: single channel, lấy is_sent=FALSE."""
    client = get_client()
    resp = client.table("signals_history").select("*").eq("is_sent", False).in_("action", ["BUY", "SELL"]).order("created_at", desc=False).execute()
    return resp.data or []


# ─────────────────────────────────────────────────────────────
# Main async logic
# ─────────────────────────────────────────────────────────────

async def send_signals_async() -> None:
    if not _BOT_TOKEN:
        logger.error("Thiếu TELEGRAM_BOT_TOKEN trong .env")
        return
    if not _VIP_CHANNEL:
        logger.error("Thiếu TELEGRAM_CHANNEL_ID hoặc TELEGRAM_VIP_CHANNEL_ID trong .env")
        return

    bot = Bot(token=_BOT_TOKEN)

    if _SPLIT_ENABLED:
        # ── Chế độ VIP/Free split ──────────────────────────────
        logger.info(f"Chế độ VIP/Free split | VIP:{_VIP_CHANNEL} | Free:{_FREE_CHANNEL} | Trễ:{_FREE_DELAY_H}h")

        vip_signals = _get_vip_pending()
        logger.info(f"VIP: {len(vip_signals)} tín hiệu chờ gửi")
        for sig in vip_signals:
            try:
                sig = _enrich_signal(sig)
                await bot.send_message(chat_id=_VIP_CHANNEL, text=_fmt_vip_message(sig), parse_mode=ParseMode.MARKDOWN_V2)
                _mark_vip_sent(sig["id"])
                logger.info(f"[VIP] Đã gửi {sig['action']} {sig['symbol']}")
            except TelegramError as e:
                logger.error(f"[VIP] Telegram lỗi {sig.get('symbol')}: {e}")
            except Exception as e:
                logger.error(f"[VIP] Lỗi {sig.get('symbol')}: {e}")

        free_signals = _get_free_pending()
        logger.info(f"Free: {len(free_signals)} tín hiệu đến hạn gửi")
        for sig in free_signals:
            try:
                await bot.send_message(chat_id=_FREE_CHANNEL, text=_fmt_free_message(sig), parse_mode=ParseMode.MARKDOWN_V2)
                _mark_free_sent(sig["id"])
                logger.info(f"[Free] Đã gửi {sig['action']} {sig['symbol']}")
            except TelegramError as e:
                logger.error(f"[Free] Telegram lỗi {sig.get('symbol')}: {e}")
            except Exception as e:
                logger.error(f"[Free] Lỗi {sig.get('symbol')}: {e}")

    else:
        # ── Chế độ single channel (backward compat Phase 1) ────
        logger.info(f"Chế độ single channel | {_VIP_CHANNEL}")
        signals = _get_legacy_pending()
        if not signals:
            logger.info("Không có tín hiệu mới để gửi.")
            return
        logger.info(f"Tìm thấy {len(signals)} tín hiệu chưa gửi.")
        for sig in signals:
            try:
                sig = _enrich_signal(sig)
                await bot.send_message(chat_id=_VIP_CHANNEL, text=_fmt_vip_message(sig), parse_mode=ParseMode.MARKDOWN_V2)
                _mark_sent_legacy(sig["id"])
                logger.info(f"Đã gửi {sig['action']} {sig['symbol']}")
            except TelegramError as e:
                logger.error(f"Telegram lỗi {sig.get('symbol')}: {e}")
            except Exception as e:
                logger.error(f"Lỗi {sig.get('symbol')}: {e}")


def main():
    logger.info("=== BẮT ĐẦU DELIVERY BOT ===")
    asyncio.run(send_signals_async())
    logger.info("=== DELIVERY BOT HOÀN TẤT ===")


if __name__ == "__main__":
    main()


# ── Dead duplicate removed ───────────────────────────────────────────────────
# (single-channel phase-1 implementation that was shadowing the VIP/Free split above)
