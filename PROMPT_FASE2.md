# PROMPT FASE 2 — Broksum Engine + Composite Scoring

> Gunakan prompt ini SETELAH Fase 1 berjalan stabil minimal 1 minggu.
> Pastikan data OHLCV sudah terkumpul dan pipeline tidak ada error.

---

## CEK SEBELUM MULAI

```
Sebelum mulai Fase 2, verifikasi:
1. GitHub Actions sudah jalan setiap hari tanpa error?
2. Data di tabel `price_data` sudah ada > 5 hari?
3. `signals` tabel ada isinya?
4. Telegram alert sudah diterima setiap hari?

Jika semua YA, kita siap Fase 2.
Jika ada yang NO, fix Fase 1 dulu.
```

---

## PROMPT UTAMA FASE 2

```
Fase 1 sudah stabil. Sekarang kita bangun Fase 2: Broker Summary Engine.

Baca ulang CLAUDE.md, docs/SIGNAL_LOGIC.md, dan docs/DATA_DICTIONARY.md
sebelum mulai.

## Yang Harus Dibuat:

### Step 1: Database Migration
Buat `scripts/migrations/002_broker_foreign.sql`:
- Tabel `broker_summary` sesuai DATA_DICTIONARY.md
- Tabel `foreign_flow` sesuai DATA_DICTIONARY.md
- Index yang direkomendasikan

### Step 2: Broker Summary Scraper
Buat `data/scrapers/broksum.py`:

Target scraping: IDX official website
URL pattern: https://www.idx.co.id/en/market-data/trading-summary/broker-summary/
Parameter: ?code={TICKER}&date={YYYYMMDD}

Juga coba Pasardana sebagai fallback:
URL: https://pasardana.id/market-data/stocks/{TICKER}/brokerage-transaction/

Fungsi yang dibutuhkan:
- `scrape_broksum_idx(ticker: str, date: str) -> pd.DataFrame`
  - Coba IDX dulu, jika gagal coba Pasardana
  - Rate limit: 2 detik antara request
  - Retry: 3x dengan exponential backoff
  - Return empty DataFrame jika semua gagal (bukan raise)
  
- `scrape_broksum_batch(tickers: list, date: str) -> dict`
  - Parallel scraping dengan max 5 concurrent requests
  - Progress bar dengan tqdm
  - Log tickers yang gagal

PENTING: Simpan raw HTML response ke logs/broksum_raw/{ticker}_{date}.html
untuk debugging kalau struktur website berubah.

Output DataFrame schema:
- ticker, date, broker_code, buy_value, sell_value, net_value,
  buy_volume, sell_volume, buy_freq, sell_freq

### Step 3: Foreign Flow Scraper
Buat `data/scrapers/foreign_flow.py`:

Target: IDX website atau RTI
URL: https://www.idx.co.id/en/market-data/trading-summary/stock-summary/

Fungsi:
- `scrape_foreign_flow(ticker: str, date: str) -> dict`
  Returns: {foreign_buy, foreign_sell, foreign_net}

### Step 4: Broker Profile Classifier
Update `config/broker_profiles.py`:
- Dictionary BROKER_CATEGORIES sesuai SIGNAL_LOGIC.md
- Fungsi `classify_broker(broker_code: str) -> str`
  Returns: "foreign_institutional", "local_institutional", "retail_heavy", "unknown"

### Step 5: Feature Engine (v2)
Update `engine/features.py`, tambahkan:

- `compute_broker_score(broksum_df: pd.DataFrame) -> float`
  Implementasi sesuai SIGNAL_LOGIC.md Layer 2

- `compute_broker_concentration(broksum_df: pd.DataFrame) -> float`
  Returns: share of top 2 brokers (0.0 - 1.0)

- `compute_avg_transaction_value(broksum_df: pd.DataFrame) -> dict`
  Returns: {avg_buy_txn, avg_sell_txn} dalam IDR

- `compute_foreign_score(foreign_df: pd.DataFrame, 
                          historical_foreign: pd.DataFrame) -> float`
  Implementasi sesuai SIGNAL_LOGIC.md Layer 3

- `detect_foreign_divergence(price_df: pd.DataFrame,
                               foreign_df: pd.DataFrame) -> bool`

### Step 6: Scorer (v2)
Update `engine/scorer.py`:

- Update `score_emiten_v2(features: dict) -> dict`
  Bobot: volume (30%) + broker (40%) + foreign (30%)
  Sesuai WEIGHTS["fase_2"] di SIGNAL_LOGIC.md

- Tambahkan ke evidence_json:
  - broker info (top buyers, concentration, avg txn)
  - foreign info (net, streak, divergence)

- Backward compatible: jika broksum tidak tersedia,
  fallback ke v1 scoring (100% volume) tapi flag "degraded_mode: true"

### Step 7: Update Main Pipeline
Update `main.py`:
- Tambahkan scraping broksum dan foreign flow
- Gunakan scorer v2 jika data tersedia, v1 jika tidak
- Log berapa persen emiten yang punya data broksum

### Step 8: Update Telegram Alert
Update `output/telegram_bot.py`:
- Format baru yang include evidence broksum
- Bedakan TIER A (full) vs TIER B (partial) vs TIER C (volume only)

### Step 9: Tests
Buat `tests/test_features.py`:
- Test compute_volume_zscore dengan data fixture
- Test compute_broker_score dengan berbagai skenario
- Test classify_broker dengan semua kategori
- Test score_emiten_v2 edge cases (missing data, all zeros, dll)

Buat `tests/fixtures/sample_broksum.json`:
- Sample data broksum yang realistic untuk testing

## Catatan Penting

1. Scraper broksum adalah komponen paling rapuh — website bisa berubah kapan saja
2. SELALU log raw HTML response untuk debugging
3. Jangan assume format data konsisten — handle semua edge case
4. Jika scraping gagal untuk > 50% emiten, kirim alert Telegram:
   "⚠️ Broksum scraping degraded — hanya X% emiten tersedia"
5. Jalankan scraper di luar jam pasar (aman setelah 16.30 WIB)
```
