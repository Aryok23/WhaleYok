-- ============================================================
-- WhaleDet IDX — Initial Schema Migration
-- Jalankan di Supabase Dashboard → SQL Editor
-- ============================================================

-- ------------------------------------------------------------
-- Tabel: emiten_universe
-- Daftar semua emiten IDX beserta metadata
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emiten_universe (
    ticker          VARCHAR(10)     PRIMARY KEY,
    name            VARCHAR(200)    NOT NULL,
    sector          VARCHAR(100),
    sub_sector      VARCHAR(100),
    papan           VARCHAR(20),                            -- Utama / Pengembangan / Akselerasi / Pemantauan
    market_cap_tier VARCHAR(10),                            -- large / mid / small / micro
    is_lq45         BOOLEAN         NOT NULL DEFAULT FALSE,
    is_idx80        BOOLEAN         NOT NULL DEFAULT FALSE,
    is_idx300       BOOLEAN         NOT NULL DEFAULT FALSE,
    konglo_group    VARCHAR(50),                            -- nullable
    listing_date    DATE,
    is_ipo_new      BOOLEAN         NOT NULL DEFAULT FALSE, -- True jika listing < 90 hari
    last_updated    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Tabel: price_data
-- OHLCV harian per emiten
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_data (
    date        DATE            NOT NULL,
    ticker      VARCHAR(10)     NOT NULL REFERENCES emiten_universe(ticker),
    open        NUMERIC(12, 2),
    high        NUMERIC(12, 2),
    low         NUMERIC(12, 2),
    close       NUMERIC(12, 2),
    volume      BIGINT,
    turnover    BIGINT,
    source      VARCHAR(20)     NOT NULL DEFAULT 'yfinance',
    PRIMARY KEY (date, ticker)
);

-- ------------------------------------------------------------
-- Tabel: broker_summary
-- Data broker summary harian (diisi mulai Fase 2)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS broker_summary (
    date                DATE            NOT NULL,
    ticker              VARCHAR(10)     NOT NULL REFERENCES emiten_universe(ticker),
    broker_code         VARCHAR(10)     NOT NULL,
    buy_value           BIGINT,
    sell_value          BIGINT,
    net_value           BIGINT  GENERATED ALWAYS AS (buy_value - sell_value) STORED,
    buy_volume          BIGINT,
    sell_volume         BIGINT,
    buy_freq            INTEGER,
    sell_freq           INTEGER,
    broker_category     VARCHAR(30),    -- foreign_institutional / local_institutional / retail_heavy
    avg_buy_txn_value   BIGINT  GENERATED ALWAYS AS (
                            CASE WHEN buy_freq > 0 THEN buy_value / buy_freq ELSE 0 END
                        ) STORED,
    PRIMARY KEY (date, ticker, broker_code)
);

-- ------------------------------------------------------------
-- Tabel: foreign_flow
-- Foreign net buy/sell harian (diisi mulai Fase 2)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS foreign_flow (
    date                DATE            NOT NULL,
    ticker              VARCHAR(10)     NOT NULL REFERENCES emiten_universe(ticker),
    foreign_buy         BIGINT,
    foreign_sell        BIGINT,
    foreign_net         BIGINT  GENERATED ALWAYS AS (foreign_buy - foreign_sell) STORED,
    foreign_net_5d      BIGINT,         -- dihitung saat insert (cumulative)
    foreign_net_10d     BIGINT,
    foreign_net_20d     BIGINT,
    foreign_buy_streak  INTEGER,        -- hari berturut-turut net buy
    foreign_divergence  BOOLEAN,        -- price turun tapi foreign net buy
    PRIMARY KEY (date, ticker)
);

-- ------------------------------------------------------------
-- Tabel: signals
-- Output sinyal per emiten per hari
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              BIGSERIAL       PRIMARY KEY,
    date            DATE            NOT NULL,
    ticker          VARCHAR(10)     NOT NULL REFERENCES emiten_universe(ticker),
    composite_score NUMERIC(5, 2)   NOT NULL,
    signal_type     VARCHAR(20)     NOT NULL,   -- STRONG_BUY / WATCH_BUY / MONITOR / DISTRIBUSI
    phase           VARCHAR(30),                -- ACCUMULATION / PRE_PUMP / dll
    tier            VARCHAR(5),                 -- A / B / C
    volume_zscore   NUMERIC(6, 2),
    volume_score    NUMERIC(5, 2),
    broker_score    NUMERIC(5, 2),              -- null di Fase 1
    foreign_score   NUMERIC(5, 2),              -- null di Fase 1
    news_score      NUMERIC(5, 2),              -- null di Fase 1-2
    evidence_json   JSONB,
    sent_to_telegram BOOLEAN        NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Tabel: news_items
-- Berita dan sentimen (diisi mulai Fase 3)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_items (
    id              BIGSERIAL       PRIMARY KEY,
    date            DATE            NOT NULL,
    tickers         VARCHAR(10)[],
    sectors         VARCHAR(100)[],
    headline        TEXT            NOT NULL,
    summary         TEXT,
    source          VARCHAR(100),
    source_weight   NUMERIC(3, 2),
    sentiment_score NUMERIC(3, 2),
    url             TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Indexes (untuk query performance)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_price_ticker_date
    ON price_data(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_broksum_ticker_date
    ON broker_summary(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_signals_date
    ON signals(date DESC);

CREATE INDEX IF NOT EXISTS idx_signals_ticker
    ON signals(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_foreign_ticker_date
    ON foreign_flow(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_news_date
    ON news_items(date DESC);

-- ============================================================
-- RLS: disabled (private project)
-- ============================================================
ALTER TABLE emiten_universe  DISABLE ROW LEVEL SECURITY;
ALTER TABLE price_data       DISABLE ROW LEVEL SECURITY;
ALTER TABLE broker_summary   DISABLE ROW LEVEL SECURITY;
ALTER TABLE foreign_flow     DISABLE ROW LEVEL SECURITY;
ALTER TABLE signals          DISABLE ROW LEVEL SECURITY;
ALTER TABLE news_items       DISABLE ROW LEVEL SECURITY;
