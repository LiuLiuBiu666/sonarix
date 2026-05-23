"""
module_dashboard/app.py
------------------------
FastAPI dashboard để monitor tín hiệu, scores và system status.

Cách chạy:
    cd crypto-hybrid-bot
    pip install fastapi uvicorn[standard] jinja2
    python -m uvicorn module_dashboard.app:app --host 0.0.0.0 --port 8000 --reload

Truy cập: http://localhost:8000
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core_shared.database import get_client
from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

app = FastAPI(
    title="Crypto Hybrid Bot Dashboard",
    description="Real-time monitoring cho Crypto Hybrid Trading Bot",
    version="1.0.0",
)

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

_SYMBOLS = [s.strip().replace("/", "") for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")]


# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/signals", response_class=JSONResponse)
async def api_signals(limit: int = 20):
    """Lấy N tín hiệu gần nhất từ signals_history."""
    try:
        client = get_client()
        resp = (
            client.table("signals_history")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"ok": True, "data": resp.data or []}
    except Exception as e:
        logger.error(f"API /signals lỗi: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/latest", response_class=JSONResponse)
async def api_latest():
    """Tín hiệu mới nhất mỗi symbol (từ view latest_signals)."""
    try:
        client = get_client()
        resp = client.table("latest_signals").select("*").execute()
        return {"ok": True, "data": resp.data or []}
    except Exception as e:
        logger.error(f"API /latest lỗi: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/tech", response_class=JSONResponse)
async def api_tech(symbol: str = "", limit: int = 10):
    """Điểm kỹ thuật gần nhất."""
    try:
        client = get_client()
        q = client.table("technical_scores").select("symbol, timeframe, tech_score, created_at").order("created_at", desc=True).limit(limit)
        if symbol:
            q = q.eq("symbol", symbol.upper())
        resp = q.execute()
        return {"ok": True, "data": resp.data or []}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/backtest", response_class=JSONResponse)
async def api_backtest():
    """Kết quả backtest mới nhất mỗi symbol."""
    try:
        client = get_client()
        results = []
        for sym in _SYMBOLS:
            resp = (
                client.table("backtest_results")
                .select("*")
                .eq("symbol", sym)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                results.append(resp.data[0])
        return {"ok": True, "data": results}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/stats", response_class=JSONResponse)
async def api_stats():
    """Thống kê tổng quan hệ thống."""
    try:
        client = get_client()
        now = datetime.now(timezone.utc)

        # Tổng tín hiệu hôm nay
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_resp = client.table("signals_history").select("action").gte("created_at", today_start).execute()
        today_signals = today_resp.data or []

        buy_count  = sum(1 for s in today_signals if s["action"] == "BUY")
        sell_count = sum(1 for s in today_signals if s["action"] == "SELL")
        hold_count = sum(1 for s in today_signals if s["action"] == "HOLD")

        # Tổng tất cả thời gian
        total_resp = client.table("signals_history").select("id", count="exact").execute()
        total_signals = total_resp.count or 0

        # Lần chạy gần nhất
        last_resp = client.table("technical_scores").select("created_at").order("created_at", desc=True).limit(1).execute()
        last_run = last_resp.data[0]["created_at"] if last_resp.data else None

        return {
            "ok": True,
            "data": {
                "today": {"buy": buy_count, "sell": sell_count, "hold": hold_count, "total": len(today_signals)},
                "all_time": {"total_signals": total_signals},
                "last_run": last_run,
                "symbols": _SYMBOLS,
                "server_time": now.isoformat(),
            },
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ─────────────────────────────────────────────────────────────
# HTML Dashboard
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", {"symbols": _SYMBOLS})


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
