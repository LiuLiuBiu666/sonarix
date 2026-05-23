/**
 * PM2 Ecosystem Config — Crypto Hybrid Bot
 *
 *   npm install -g pm2
 *   pm2 start ecosystem.config.js
 *   pm2 save
 *   pm2 status / pm2 logs <name> / pm2 restart <name>
 */

const path = require("path");
const PY  = path.join(__dirname, "venv", "Scripts", "python.exe");
const CWD = __dirname;

module.exports = {
  apps: [
    // Hourly trading pipeline
    {
      name:         "bot",
      cwd:          CWD,
      script:       PY,
      args:         "run_all.py",
      interpreter:  "none",
      cron_restart: "0 * * * *",
      autorestart:  false,
      watch:        false,
      env: { NODE_ENV: "production", PYTHONIOENCODING: "utf-8" },
      out_file:   "logs/pm2-bot.log",
      error_file: "logs/pm2-bot-error.log",
      time:       true,
    },

    // Daily backtest at 03:00 UTC
    {
      name:         "backtest",
      cwd:          CWD,
      script:       PY,
      args:         "-m module_backtest.main_backtest",
      interpreter:  "none",
      cron_restart: "0 3 * * *",
      autorestart:  false,
      watch:        false,
      env: {
        NODE_ENV:         "production",
        PYTHONIOENCODING: "utf-8",
        HISTORY_LIMIT:    "2000",
        HOLD_CANDLES:     "12",
        BACKTEST_SAVE_DB: "true",
      },
      out_file:   "logs/pm2-backtest.log",
      error_file: "logs/pm2-backtest-error.log",
      time:       true,
    },

    // FastAPI dashboard, always running
    {
      name:        "dashboard",
      cwd:         CWD,
      script:      PY,
      args:        "-m uvicorn module_dashboard.app:app --host 0.0.0.0 --port 8000 --workers 1",
      interpreter: "none",
      autorestart: true,
      watch:       false,
      env: { NODE_ENV: "production", PYTHONIOENCODING: "utf-8" },
      out_file:   "logs/pm2-dashboard.log",
      error_file: "logs/pm2-dashboard-error.log",
      time:       true,
    },
  ],
};
