-- ============================================================
-- WhaleDet IDX — Fase 2 Schema Migration
-- Jalankan di Supabase Dashboard → SQL Editor
-- ============================================================
-- Menyesuaikan kolom broker_summary dan foreign_flow dengan
-- output scraper Fase 2.
-- Aman dijalankan berulang (IF NOT EXISTS / IF EXISTS).
-- ============================================================

-- ------------------------------------------------------------
-- Recreate broker_summary dengan kolom yang benar
-- (Tabel kosong di Fase 1, aman di-drop)
-- ------------------------------------------------------------
DROP TABLE IF EXISTS broker_summary CASCADE;

CREATE TABLE broker_summary (
    date            DATE            NOT NULL,
    ticker          VARCHAR(10)     NOT NULL REFERENCES emiten_universe(ticker),
    broker_code     VARCHAR(10)     NOT NULL,
    buy_value       BIGINT          DEFAULT 0,
    sell_value      BIGINT          DEFAULT 0,
    net_value       BIGINT          GENERATED ALWAYS AS (buy_value - sell_value) STORED,
    buy_volume      BIGINT          DEFAULT 0,
    sell_volume     BIGINT          DEFAULT 0,
    net_volume      BIGINT          GENERATED ALWAYS AS (buy_volume - sell_volume) STORED,
    freq_buy        INTEGER         DEFAULT 0,
    freq_sell       INTEGER         DEFAULT 0,
    category        VARCHAR(20),    -- ASING / INSTITUSI / RETAIL
    PRIMARY KEY (date, ticker, broker_code)
);

CREATE INDEX IF NOT EXISTS idx_broksum_ticker_date
    ON broker_summary(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_broksum_date
    ON broker_summary(date DESC);

-- ------------------------------------------------------------
-- Recreate foreign_flow dengan kolom yang benar
-- (Tabel kosong di Fase 1, aman di-drop)
-- ------------------------------------------------------------
DROP TABLE IF EXISTS foreign_flow CASCADE;

CREATE TABLE foreign_flow (
    date                    DATE        NOT NULL,
    ticker                  VARCHAR(10) NOT NULL REFERENCES emiten_universe(ticker),
    foreign_buy             BIGINT      DEFAULT 0,
    foreign_sell            BIGINT      DEFAULT 0,
    foreign_net             BIGINT      GENERATED ALWAYS AS (foreign_buy - foreign_sell) STORED,
    foreign_buy_volume      BIGINT      DEFAULT 0,
    foreign_sell_volume     BIGINT      DEFAULT 0,
    foreign_net_volume      BIGINT      GENERATED ALWAYS AS (foreign_buy_volume - foreign_sell_volume) STORED,
    PRIMARY KEY (date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_foreign_flow_ticker_date
    ON foreign_flow(ticker, date DESC);

-- ------------------------------------------------------------
-- RLS off (sama seperti tabel lain)
-- ------------------------------------------------------------
ALTER TABLE broker_summary  DISABLE ROW LEVEL SECURITY;
ALTER TABLE foreign_flow    DISABLE ROW LEVEL SECURITY;
