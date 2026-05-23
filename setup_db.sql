-- ============================================================
-- CRYPTO HYBRID BOT — DATABASE SCHEMA
-- Chạy file này trong Supabase SQL Editor
-- Dashboard: https://supabase.com/dashboard → SQL Editor
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- Bảng 1: technical_scores
-- Lưu điểm kỹ thuật sau mỗi lần phân tích
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS technical_scores (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    timeframe       VARCHAR(10)     NOT NULL DEFAULT '4h',
    tech_score      INT             NOT NULL CHECK (tech_score BETWEEN -100 AND 100),
    indicators_data JSONB,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Index để query nhanh theo symbol và thời gian
CREATE INDEX IF NOT EXISTS idx_tech_symbol_time
    ON technical_scores (symbol, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Bảng 2: sentiment_scores
-- Lưu điểm tâm lý từ Gemini sau mỗi lần phân tích tin tức
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentiment_scores (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    sentiment_score INT             NOT NULL CHECK (sentiment_score BETWEEN -100 AND 100),
    summary_reason  TEXT,
    source_count    INT             DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sent_symbol_time
    ON sentiment_scores (symbol, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Bảng 3: signals_history
-- Lưu tín hiệu hợp nhất cuối cùng (BUY/SELL/HOLD)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals_history (
    id                  SERIAL PRIMARY KEY,
    symbol              VARCHAR(20)     NOT NULL,
    final_score         FLOAT           NOT NULL,
    action              VARCHAR(10)     NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    win_rate_estimated  FLOAT           CHECK (win_rate_estimated BETWEEN 0 AND 1),
    is_sent             BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Phase 3A: VIP/Free channel split
    is_sent_vip         BOOLEAN         NOT NULL DEFAULT FALSE,
    is_sent_free        BOOLEAN         NOT NULL DEFAULT FALSE,
    free_send_after     TIMESTAMPTZ     DEFAULT (NOW() + INTERVAL '24 hours'),
    -- Phase 3B: Discord delivery (VIP/Free/PRO split)
    is_sent_discord_vip     BOOLEAN         NOT NULL DEFAULT FALSE,
    is_sent_discord_free    BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_unsent
    ON signals_history (is_sent, created_at DESC)
    WHERE is_sent = FALSE;

CREATE INDEX IF NOT EXISTS idx_signals_vip_unsent
    ON signals_history (is_sent_vip, created_at DESC)
    WHERE is_sent_vip = FALSE;

CREATE INDEX IF NOT EXISTS idx_signals_free_pending
    ON signals_history (is_sent_free, free_send_after)
    WHERE is_sent_free = FALSE;

CREATE INDEX IF NOT EXISTS idx_signals_discord_vip
    ON signals_history (is_sent_discord_vip, created_at DESC)
    WHERE is_sent_discord_vip = FALSE;

CREATE INDEX IF NOT EXISTS idx_signals_discord_free
    ON signals_history (is_sent_discord_free, free_send_after)
    WHERE is_sent_discord_free = FALSE;

CREATE INDEX IF NOT EXISTS idx_signals_symbol_time
    ON signals_history (symbol, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Bảng 4: backtest_results  (Phase 2C)
-- Lưu kết quả backtest để theo dõi hiệu suất tín hiệu theo thời gian
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_results (
    id                  SERIAL PRIMARY KEY,
    symbol              VARCHAR(20)     NOT NULL,
    timeframe           VARCHAR(10)     NOT NULL DEFAULT '4h',
    hold_candles        INT             NOT NULL DEFAULT 12,
    history_limit       INT             NOT NULL DEFAULT 2000,
    total_trades        INT             NOT NULL DEFAULT 0,
    win_rate            FLOAT           CHECK (win_rate BETWEEN 0 AND 1),
    avg_win_pct         FLOAT,
    avg_loss_pct        FLOAT,
    profit_factor       FLOAT,
    total_pnl_pct       FLOAT,
    expectancy_pct      FLOAT,
    sharpe_ratio        FLOAT,
    max_drawdown_pct    FLOAT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_symbol_time
    ON backtest_results (symbol, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Row Level Security (RLS) — Tắt để backend dùng service_role
-- ─────────────────────────────────────────────────────────────
ALTER TABLE technical_scores  DISABLE ROW LEVEL SECURITY;
ALTER TABLE sentiment_scores  DISABLE ROW LEVEL SECURITY;
ALTER TABLE signals_history   DISABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_results  DISABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────
-- View tiện lợi: tín hiệu mới nhất mỗi symbol
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW latest_signals AS
SELECT DISTINCT ON (symbol)
    id, symbol, final_score, action, win_rate_estimated,
    is_sent, is_sent_vip, is_sent_free, is_sent_discord_vip, is_sent_discord_free, free_send_after, created_at
FROM signals_history
ORDER BY symbol, created_at DESC;

-- ─────────────────────────────────────────────────────────────
-- MIGRATION: Nếu bảng signals_history đã tồn tại từ Phase 1/3A,
-- chạy các lệnh này để thêm cột (bỏ qua nếu cột đã có):
-- ─────────────────────────────────────────────────────────────
-- ALTER TABLE signals_history ADD COLUMN IF NOT EXISTS is_sent_vip BOOLEAN NOT NULL DEFAULT FALSE;
-- ALTER TABLE signals_history ADD COLUMN IF NOT EXISTS is_sent_free BOOLEAN NOT NULL DEFAULT FALSE;
-- ALTER TABLE signals_history ADD COLUMN IF NOT EXISTS free_send_after TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '24 hours');
-- ALTER TABLE signals_history ADD COLUMN IF NOT EXISTS is_sent_discord_vip BOOLEAN NOT NULL DEFAULT FALSE;
-- ALTER TABLE signals_history ADD COLUMN IF NOT EXISTS is_sent_discord_free BOOLEAN NOT NULL DEFAULT FALSE;

