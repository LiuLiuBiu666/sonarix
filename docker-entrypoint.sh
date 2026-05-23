#!/bin/bash
# docker-entrypoint.sh — cron daemon + FastAPI dashboard (Railway-ready)

set -e

echo "=== Crypto Hybrid Bot Starting ==="
echo "UTC: $(date -u)"

# Railway provides $PORT; fall back to 8000 for local docker
PORT="${PORT:-8000}"

# Start cron daemon in the background
service cron start
echo "[OK] Cron daemon started"

# Warm-up pipeline run (non-blocking; container stays alive via dashboard)
echo "[BOOT] Running initial pipeline..."
python run_all.py >> /app/logs/boot.log 2>&1 &

# Start FastAPI dashboard in foreground to keep container alive
echo "[WEB] Dashboard listening on 0.0.0.0:${PORT}"
exec python -m uvicorn module_dashboard.app:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --log-level info
