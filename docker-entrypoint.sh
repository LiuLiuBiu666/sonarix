#!/bin/bash
# docker-entrypoint.sh — cron daemon + FastAPI dashboard (Railway-ready)

set -e

echo "=== Crypto Hybrid Bot Starting ==="
echo "UTC: $(date -u)"

# Railway provides $PORT; fall back to 8000 for local docker
PORT="${PORT:-8000}"

# Start cron daemon in the background (best-effort — don't block boot)
service cron start || echo "[WARN] cron daemon failed to start (skipping)"
echo "[OK] Boot continues"

# Start FastAPI dashboard in foreground immediately so Railway healthcheck succeeds.
# Pipeline runs only via crontab (hourly) — no warm-up at boot to avoid blocking the port.
echo "[WEB] Dashboard listening on 0.0.0.0:${PORT}"
exec python -m uvicorn module_dashboard.app:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --log-level info
