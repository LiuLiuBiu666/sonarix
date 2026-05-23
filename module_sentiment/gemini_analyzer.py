"""
module_sentiment/gemini_analyzer.py
-------------------------------------
Gửi danh sách tiêu đề tin tức sang Groq API để phân tích sắc thái.
(Thay thế Gemini — free tier không giới hạn billing)
Trả về điểm sentiment (-100 đến +100) và lý do tóm tắt.
"""

import json
import os
import re
import time

from groq import Groq
from dotenv import load_dotenv

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
_MAX_RETRIES  = 3
_RETRY_DELAY  = 5  # giây


def _build_prompt(symbol: str, headlines: list[str]) -> str:
    """Build the sentiment-analysis prompt (English output)."""
    headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
    return f"""You are a senior financial-markets sentiment analyst covering crypto assets.
The system has just collected {len(headlines)} of the latest news headlines about {symbol}.
Score the OVERALL market sentiment conveyed by this batch on a scale from -100
(extreme fear / capitulation / fully bearish) to +100 (extreme euphoria / fully bullish),
where 0 is balanced or neutral.

HEADLINES:
{headlines_text}

Return ONLY a single valid JSON object — no markdown, no preface, no trailing text:
{{
  "score": <integer between -100 and 100>,
  "reason": "<a detailed English explanation, 3 to 5 sentences (roughly 60-120 words). Cover: (1) the dominant bullish drivers if any, (2) the dominant bearish drivers if any, (3) overall net tone, and (4) any notable catalysts or risks traders should watch. Write in clear, professional English. Do NOT mention article numbers.>",
  "short_term_outlook": "<a forward-looking call for the NEXT 4 TO 24 HOURS, 2 to 3 sentences in English. State the most likely directional bias, key levels or catalysts to monitor, and how a trader should position. Be concrete, not generic.>",
  "long_term_outlook": "<a forward-looking call for the NEXT 1 TO 4 WEEKS, 2 to 3 sentences in English. State the broader trend bias, structural drivers, and any macro or on-chain catalysts to watch. Be concrete, not generic.>"
}}"""


def _parse_response(raw_text: str) -> dict:
    """Trích xuất JSON từ phản hồi LLM."""
    try:
        return json.loads(raw_text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*?\"score\".*?\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Không thể parse JSON từ phản hồi: {raw_text[:200]}")


def analyze_sentiment(symbol: str, headlines: list[str]) -> dict:
    """
    Gọi Groq API để phân tích sắc thái từ danh sách tiêu đề.

    Args:
        symbol:    Mã coin (dùng trong prompt)
        headlines: Danh sách tiêu đề tin tức

    Returns:
        dict với keys: score (int), reason (str)
    """
    if not _GROQ_API_KEY:
        logger.warning("GROQ_API_KEY chưa cấu hình. Trả về điểm trung tính.")
        return {"score": 0, "reason": "No Groq API key configured", "short_term_outlook": "", "long_term_outlook": ""}

    client = Groq(api_key=_GROQ_API_KEY)
    prompt = _build_prompt(symbol, headlines)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"Gọi Groq API cho {symbol} (lần {attempt}/{_MAX_RETRIES})...")
            response = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024,
            )
            raw_text = response.choices[0].message.content
            result = _parse_response(raw_text)

            score = int(result.get("score", 0))
            score = max(-100, min(100, score))
            reason = str(result.get("reason", "No reason provided")).strip()
            short_term = str(result.get("short_term_outlook", "")).strip()
            long_term  = str(result.get("long_term_outlook", "")).strip()

            logger.info(f"Groq chấm điểm {symbol}: {score:+d} — {reason[:120]}")
            return {
                "score": score,
                "reason": reason,
                "short_term_outlook": short_term,
                "long_term_outlook":  long_term,
            }

        except Exception as e:
            err_str = str(e)
            logger.warning(f"Lỗi Groq lần {attempt}: {e}")
            if "rate_limit" in err_str.lower() or "429" in err_str:
                logger.warning("Groq rate limit — chờ 10s rồi retry...")
                time.sleep(10)
            elif attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
            else:
                logger.error(f"Groq thất bại sau {_MAX_RETRIES} lần. Trả về điểm 0.")
                return {"score": 0, "reason": f"Groq API error: {err_str[:100]}", "short_term_outlook": "", "long_term_outlook": ""}

    return {"score": 0, "reason": "Groq API did not respond after multiple attempts", "short_term_outlook": "", "long_term_outlook": ""}

