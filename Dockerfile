# ────────────────────────────────────────────────────────────
# Dockerfile — Crypto Hybrid Bot
# Build: docker build -t crypto-hybrid-bot .
# Run:   docker run --env-file .env -p 8000:8000 crypto-hybrid-bot
# ────────────────────────────────────────────────────────────

FROM python:3.13-slim

# Metadata
LABEL maintainer="crypto-hybrid-bot"
LABEL description="Crypto Hybrid Trading Bot — Technical + Sentiment AI"

# Tránh interactive prompts khi cài apt packages
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài system deps (cần cho một số Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Thư mục làm việc
WORKDIR /app

# Copy requirements trước (cache layer)
COPY requirements.txt .
COPY module_technical/requirements.txt ./module_technical/requirements.txt
COPY module_sentiment/requirements.txt ./module_sentiment/requirements.txt
COPY module_delivery/requirements.txt ./module_delivery/requirements.txt

# Cài tất cả packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r module_technical/requirements.txt && \
    pip install --no-cache-dir -r module_sentiment/requirements.txt && \
    pip install --no-cache-dir -r module_delivery/requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn[standard] jinja2

# Copy toàn bộ source code
COPY . .

# Tạo thư mục logs
RUN mkdir -p logs

# Crontab cho cả pipeline chính và backtest (ghộp 1 lần — tránh overwrite)
RUN printf '%s\n%s\n' \
    "0 * * * * cd /app && python run_all.py >> /app/logs/cron.log 2>&1" \
    "0 3 * * * cd /app && python -m module_backtest.main_backtest >> /app/logs/backtest.log 2>&1" \
    | crontab -

# Expose dashboard port (Railway sẽ inject $PORT)
EXPOSE 8000

# Entrypoint: chạy cron daemon + FastAPI dashboard
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

CMD ["/docker-entrypoint.sh"]
