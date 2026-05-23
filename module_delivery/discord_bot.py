"""
module_delivery/discord_bot.py
--------------------------------
Gửi tín hiệu BUY/SELL lên 3 kênh Discord theo tầng dịch vụ:

  PRO Channel  : Tín hiệu NGAY LẬP TỨC — full data, top 20 coin ($199/tháng)
  VIP Channel  : Tín hiệu NGAY LẬP TỨC — full data, top 8 coin ($89/tháng)
  Free Channel : Tín hiệu TRỄ 24 GIỜ   — thông tin cơ bản, CTA upgrade ($0)

Cách chạy:
    cd crypto-hybrid-bot
    python -m module_delivery.discord_bot

Cấu hình .env:
    DISCORD_VIP_WEBHOOK_URL=https://discord.com/api/webhooks/...
    DISCORD_PRO_WEBHOOK_URL=https://discord.com/api/webhooks/...
    DISCORD_FREE_WEBHOOK_URL=https://discord.com/api/webhooks/...
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core_shared.database import get_client
from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

_VIP_WEBHOOK    = os.getenv("DISCORD_VIP_WEBHOOK_URL", "")
_PRO_WEBHOOK    = os.getenv("DISCORD_PRO_WEBHOOK_URL", "")
_FREE_WEBHOOK   = os.getenv("DISCORD_FREE_WEBHOOK_URL", "")
_SPLIT_ENABLED  = bool(_VIP_WEBHOOK and _FREE_WEBHOOK)
_TIMEOUT        = 10  # giây

# Top 8 coins — VIP tier (highest-liquidity majors)
_VIP_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
}

# Top 20 coins — PRO tier (extended majors + L1/L2 leaders)
_PRO_SYMBOLS = _VIP_SYMBOLS | {
    "DOTUSDT", "MATICUSDT", "LINKUSDT", "UNIUSDT",
    "LTCUSDT", "ATOMUSDT", "NEARUSDT", "FTMUSDT",
    "INJUSDT", "ARBUSDT",  "OPUSDT",   "SUIUSDT",
}

# ─────────────────────────────────────────────────────────────
# Embed colors and labels (professional, no emoji)
# ─────────────────────────────────────────────────────────────
_COLOR = {"BUY": 0x1F8B4C, "SELL": 0xC0392B, "HOLD": 0x5D6D7E}
_LABEL = {"BUY": "LONG", "SELL": "SHORT", "HOLD": "NEUTRAL"}

# Tier thresholds
_PRO_MIN_ABS_SCORE = 40.0   # PRO: top-20 universe, full depth
_VIP_MIN_ABS_SCORE = 40.0   # VIP: top-8 universe, condensed format


def _score_bar(score: float, max_score: float = 100.0) -> str:
    pct    = min(abs(score) / max_score, 1.0)
    filled = int(pct * 10)
    return "█" * filled + "░" * (10 - filled)


def _long_term_bias(score: float) -> tuple[str, int]:
    """Map a final score to a long-term market bias label and color."""
    if score >= 30:
        return "BULLISH", 0x1F8B4C
    if score <= -30:
        return "BEARISH", 0xC0392B
    return "NEUTRAL", 0x5D6D7E


# ─────────────────────────────────────────────────────────────
# Lấy dữ liệu từ Supabase
# ─────────────────────────────────────────────────────────────

def _enrich_scores(signal: dict) -> dict:
    client = get_client()
    symbol = signal["symbol"]
    tech = (
        client.table("technical_scores")
        .select("tech_score")
        .eq("symbol", symbol)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    sent = (
        client.table("sentiment_scores")
        .select("sentiment_score, summary_reason")
        .eq("symbol", symbol)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if tech.data:
        signal["tech_score"] = tech.data[0]["tech_score"]
    if sent.data:
        signal["sentiment_score"] = sent.data[0]["sentiment_score"]
        raw_reason = sent.data[0].get("summary_reason", "") or ""
        # summary_reason is a JSON blob {reason, short_term_outlook, long_term_outlook}
        try:
            parsed = json.loads(raw_reason)
            signal["summary_reason"]     = parsed.get("reason", "") or ""
            signal["short_term_outlook"] = parsed.get("short_term_outlook", "") or ""
            signal["long_term_outlook"]  = parsed.get("long_term_outlook", "") or ""
        except (json.JSONDecodeError, TypeError):
            # Legacy plain-text rows
            signal["summary_reason"]     = raw_reason
            signal["short_term_outlook"] = ""
            signal["long_term_outlook"]  = ""
    return signal


def _get_vip_pending() -> list[dict]:
    """Tín hiệu VIP/PRO chưa gửi Discord (gửi ngay, không delay)."""
    client = get_client()
    return (
        client.table("signals_history")
        .select("*")
        .eq("is_sent_discord_vip", False)
        .in_("action", ["BUY", "SELL"])
        .order("created_at", desc=False)
        .execute()
    ).data or []


def _get_free_pending() -> list[dict]:
    """Tín hiệu Free chưa gửi Discord (chỉ lấy khi đã đến giờ delay)."""
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    return (
        client.table("signals_history")
        .select("*")
        .eq("is_sent_discord_free", False)
        .in_("action", ["BUY", "SELL"])
        .lte("free_send_after", now_iso)
        .order("created_at", desc=False)
        .execute()
    ).data or []


def _mark_vip_sent(signal_id: int) -> None:
    get_client().table("signals_history").update({"is_sent_discord_vip": True}).eq("id", signal_id).execute()


def _mark_free_sent(signal_id: int) -> None:
    get_client().table("signals_history").update({"is_sent_discord_free": True}).eq("id", signal_id).execute()


# ─────────────────────────────────────────────────────────────
# Tạo Discord Embed payload
# ─────────────────────────────────────────────────────────────

def _fmt_pro_embed(signal: dict) -> dict:
    """PRO tier — high-conviction signals only, full breakdown."""
    action       = signal.get("action", "HOLD")
    symbol       = signal.get("symbol", "???")
    score        = signal.get("final_score", 0.0)
    win_pct      = signal.get("win_rate_estimated") or 0
    reason       = signal.get("summary_reason", "")
    short_term   = signal.get("short_term_outlook", "")
    ts           = datetime.now(timezone.utc).strftime("%H:%M UTC · %d %b %Y")
    bar          = _score_bar(score)

    t = signal.get("tech_score")
    s = signal.get("sentiment_score")
    conviction = "HIGH" if abs(score) >= 75 else "MODERATE"

    fields = [
        {"name": "Action",            "value": f"`{_LABEL.get(action, action)}`",      "inline": True},
        {"name": "Conviction",        "value": f"`{conviction}`",                      "inline": True},
        {"name": "Win Rate",          "value": f"`{win_pct * 100:.0f}%`",              "inline": True},
        {"name": "Confluence Score",  "value": f"`{score:+.1f} / 100`\n`{bar}`",       "inline": False},
        {
            "name":   "Technical  /  Sentiment",
            "value":  (f"`{t:+}`" if t is not None else "`N/A`") + "   |   " + (f"`{s:+}`" if s is not None else "`N/A`"),
            "inline": False,
        },
    ]
    if short_term:
        fields.append({"name": "Next Short-Term Outlook (4-24h)", "value": short_term[:1024], "inline": False})
    if reason:
        fields.append({"name": "Analyst Commentary", "value": reason[:1024], "inline": False})

    return {"embeds": [{
        "title":  f"PRO  |  {symbol}  —  {_LABEL.get(action, action)}",
        "color":  _COLOR.get(action, 0x5D6D7E),
        "fields": fields,
        "footer": {"text": f"Sonarix PRO  ·  {ts}"},
    }]}


def _fmt_vip_embed(signal: dict) -> dict:
    """VIP tier — qualifying signals, concise format with short-term outlook."""
    action     = signal.get("action", "HOLD")
    symbol     = signal.get("symbol", "???")
    score      = signal.get("final_score", 0.0)
    win_pct    = signal.get("win_rate_estimated") or 0
    short_term = signal.get("short_term_outlook", "")
    ts         = datetime.now(timezone.utc).strftime("%H:%M UTC · %d %b %Y")
    bar        = _score_bar(score)

    fields = [
        {"name": "Action",    "value": f"`{_LABEL.get(action, action)}`", "inline": True},
        {"name": "Score",     "value": f"`{score:+.1f}` {bar}",           "inline": True},
        {"name": "Win Rate",  "value": f"`{win_pct * 100:.0f}%`",         "inline": True},
    ]
    if short_term:
        fields.append({"name": "Next Short-Term Outlook (4-24h)", "value": short_term[:1024], "inline": False})

    return {"embeds": [{
        "title":  f"VIP  |  {symbol}  —  {_LABEL.get(action, action)}",
        "color":  _COLOR.get(action, 0x5D6D7E),
        "fields": fields,
        "footer": {"text": f"Sonarix VIP  ·  {ts}"},
    }]}


def _fmt_free_embed(signal: dict) -> dict:
    """Free tier — long-term outlook only (no entry signals). Delayed 24h."""
    symbol      = signal.get("symbol", "???")
    score       = signal.get("final_score", 0.0)
    long_term   = signal.get("long_term_outlook", "")
    bias, color = _long_term_bias(score)
    ts          = datetime.now(timezone.utc).strftime("%H:%M UTC · %d %b %Y")

    fields = [
        {"name": "Long-Term Bias", "value": f"`{bias}`", "inline": True},
    ]
    if long_term:
        fields.append({"name": "Long-Term Outlook (1-4 weeks)", "value": long_term[:1024], "inline": False})
    fields.append({
        "name":  "Upgrade",
        "value": "Real-time entries are reserved for **VIP** members. "
                 "High-conviction trades with full analyst commentary are reserved for **PRO**.",
        "inline": False,
    })

    return {"embeds": [{
        "title":  f"FREE  |  {symbol}  —  Long-Term Outlook",
        "color":  color,
        "fields": fields,
        "footer": {"text": f"Sonarix Free  ·  {ts}"},
    }]}


# ─────────────────────────────────────────────────────────────
# Gửi qua webhook
# ─────────────────────────────────────────────────────────────

def _post(webhook_url: str, payload: dict, label: str) -> bool:
    try:
        resp = requests.post(webhook_url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.HTTPError as e:
        logger.error(f"Discord {label} HTTP {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Discord {label} error: {e}")
    return False


# ─────────────────────────────────────────────────────────────
# Logic chính
# ─────────────────────────────────────────────────────────────

async def send_signals_async() -> None:
    """Entry point — gửi VIP/PRO ngay, Free sau delay."""
    if not _SPLIT_ENABLED:
        logger.error("DISCORD_VIP_WEBHOOK_URL hoặc DISCORD_FREE_WEBHOOK_URL chưa cấu hình — bỏ qua.")
        return

    # ── VIP + PRO (real-time delivery) ────────────────────────
    vip_signals = _get_vip_pending()
    if vip_signals:
        logger.info(f"Discord VIP/PRO: {len(vip_signals)} pending signal(s).")
        for sig in vip_signals:
            sig    = _enrich_scores(sig)
            symbol = sig.get("symbol", "")
            score  = sig.get("final_score", 0.0) or 0.0

            # PRO — top-20 universe, full depth
            if _PRO_WEBHOOK and symbol in _PRO_SYMBOLS and abs(score) >= _PRO_MIN_ABS_SCORE:
                _post(_PRO_WEBHOOK, _fmt_pro_embed(sig), f"PRO/{symbol}")

            # VIP — top-8 universe, condensed format
            if symbol in _VIP_SYMBOLS and abs(score) >= _VIP_MIN_ABS_SCORE:
                _post(_VIP_WEBHOOK, _fmt_vip_embed(sig), f"VIP/{symbol}")

            _mark_vip_sent(sig["id"])
            logger.info(f"Discord OK VIP/PRO: {sig['action']} {symbol} (score {score:+.1f})")
    else:
        logger.info("Discord VIP/PRO: no new signals.")

    # ── Free (long-term outlook, delayed 24h) ─────────────────
    free_signals = _get_free_pending()
    if free_signals:
        logger.info(f"Discord Free: {len(free_signals)} signal(s) ready to publish.")
        for sig in free_signals:
            sig = _enrich_scores(sig)
            _post(_FREE_WEBHOOK, _fmt_free_embed(sig), f"Free/{sig.get('symbol', '?')}")
            _mark_free_sent(sig["id"])
            logger.info(f"Discord OK Free: {sig.get('symbol')} long-term outlook")
    else:
        logger.info("Discord Free: nothing scheduled.")


def main() -> None:
    logger.info("=== BẮT ĐẦU DISCORD DELIVERY ===")
    asyncio.run(send_signals_async())
    logger.info("=== DISCORD DELIVERY HOÀN TẤT ===")


if __name__ == "__main__":
    main()