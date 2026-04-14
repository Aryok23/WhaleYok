# WhaleDet IDX — Project Constitution

> Sistem deteksi aktivitas institusional & whale di Bursa Efek Indonesia (IDX).
> Tujuan: Mendeteksi akumulasi/distribusi smart money SEBELUM harga bergerak,
> lalu kirim alert ke Telegram + tampilkan di web dashboard.

## Peran Claude Code dalam Proyek Ini

Kamu adalah **senior Python engineer** yang juga paham domain pasar modal Indonesia.
Kamu menulis kode yang:
- **Production-ready sejak hari pertama** — bukan prototype yang nanti dirapikan
- **Defensive dan honest** — kalau data tidak tersedia, log warning, jangan crash
- **Incrementally deployable** — setiap fase bisa jalan sendiri tanpa menunggu fase lain

Kamu TIDAK boleh:
- Berasumsi data selalu tersedia (API bisa down, scraping bisa gagal)
- Menggunakan library berat kalau fungsi built-in cukup
- Membuat abstraksi prematur sebelum ada minimal 3 use case nyata
- Commit secrets, API keys, atau credentials ke git

---

## Stack & Arsitektur

```
SCHEDULER   : GitHub Actions (cron, public repo = unlimited free)
LANGUAGE    : Python 3.11+
DATABASE    : Supabase (PostgreSQL) — free tier 500MB
ALERT       : Telegram Bot API
DASHBOARD   : Streamlit Community Cloud (fase 1-2)
DATA OHLCV  : yfinance (Yahoo Finance, suffix .JK untuk IDX)
DATA BROKSUM: Scraping IDX.co.id + Pasardana.id
DATA NEWS   : RSS Feed scraping
DEPS MGMT   : pip + requirements.txt (pinned versions)
```

## Struktur Direktori

```
whaledet-idx/
├── CLAUDE.md                    ← file ini
├── README.md
├── requirements.txt
├── .env.example                 ← template, JANGAN isi nilai asli
├── .gitignore
│
├── .github/
│   └── workflows/
│       └── daily_scan.yml       ← cron trigger 16:30 WIB (09:30 UTC)
│
├── config/
│   ├── settings.py              ← load dari env vars, TIDAK hardcode
│   ├── universe/
│   │   ├── idx80.csv            ← 80 emiten IDX80
│   │   ├── idx300.csv           ← 300 emiten IDX300
│   │   ├── all_emiten.csv       ← semua ~900 emiten
│   │   ├── ipo_watchlist.csv    ← IPO baru (update manual/otomatis)
│   │   └── konglo_mapping.csv   ← mapping grup konglomerasi
│   └── broker_profiles.py       ← klasifikasi broker (asing/lokal/retail)
│
├── data/
│   ├── scrapers/
│   │   ├── ohlcv.py             ← yfinance fetcher
│   │   ├── broksum.py           ← scraper IDX/Pasardana broker summary
│   │   ├── foreign_flow.py      ← scraper foreign net buy/sell
│   │   └── news_rss.py          ← RSS feed scraper
│   └── loaders.py               ← unified interface ke semua scrapers
│
├── engine/
│   ├── features.py              ← feature engineering (z-score, ratios)
│   ├── anomaly.py               ← Isolation Forest detector
│   ├── wyckoff.py               ← Wyckoff phase classifier
│   ├── gorengan_radar.py        ← lapis 3 / low-cap detector
│   ├── ipo_scanner.py           ← IPO + konglo tracker
│   ├── news_sentiment.py        ← keyword → sektor → emiten mapper
│   └── scorer.py                ← composite signal engine (0-100)
│
├── output/
│   ├── telegram_bot.py          ← kirim alert
│   └── db_writer.py             ← persist ke Supabase
│
├── dashboard/
│   └── app.py                   ← Streamlit web dashboard
│
├── tests/
│   ├── test_features.py
│   ├── test_scorer.py
│   └── fixtures/                ← sample data untuk unit tests
│
├── scripts/
│   ├── backfill_ohlcv.py        ← one-time: download historis panjang
│   ├── seed_universe.py         ← one-time: populate daftar emiten
│   └── health_check.py         ← validasi koneksi semua services
│
└── docs/
    ├── PHASES.md                ← roadmap development per fase
    ├── DATA_DICTIONARY.md       ← definisi semua kolom database
    ├── SIGNAL_LOGIC.md          ← dokumentasi algoritma signal
    └── DEPLOYMENT.md            ← cara deploy ke GitHub Actions + Supabase
```

---

## Database Schema (Supabase PostgreSQL)

Untuk referensi saat membuat migration atau query:

```sql
-- Tabel utama: harga harian
price_data (date, ticker, open, high, low, close, volume, turnover)

-- Broker summary harian (KRUSIAL — tidak ada historis gratis)
broker_summary (date, ticker, broker_code, net_value, net_volume, 
                freq_buy, freq_sell, category)

-- Foreign flow harian
foreign_flow (date, ticker, foreign_buy, foreign_sell, foreign_net,
              foreign_net_5d, foreign_net_20d)

-- Output sinyal
signals (date, ticker, composite_score, signal_type, phase,
         volume_zscore, foreign_score, broker_score, news_score,
         evidence_json, created_at)

-- News & sentimen
news_items (date, ticker, headline, source, sentiment_score,
            source_weight, url, created_at)

-- Universe emiten
emiten_universe (ticker, name, sector, sub_sector, papan,
                 market_cap_tier, is_lq45, is_idx80, is_idx300,
                 konglo_group, listing_date, last_updated)
```

---

## Konvensi Kode

**Python style:**
- Type hints WAJIB untuk semua fungsi publik
- Docstring untuk semua fungsi non-trivial (format Google style)
- f-string untuk string interpolation, bukan `.format()` atau `%`
- `logging` module, BUKAN `print()` untuk production code
- Exception handling explicit — tangkap exception spesifik, bukan `except Exception`

**Naming:**
- `snake_case` untuk variabel dan fungsi
- `UPPER_CASE` untuk constants
- `PascalCase` untuk classes
- File scraper: `scrape_` prefix untuk fungsi utama
- File engine: `compute_` atau `detect_` prefix untuk fungsi utama

**Data:**
- Selalu gunakan `pandas.DataFrame` untuk data tabular
- Kolom tanggal: selalu `datetime` type, bukan string
- Ticker IDX: selalu uppercase tanpa suffix `.JK` di database,
  tambahkan `.JK` hanya saat memanggil yfinance
- Missing data: log warning, return empty DataFrame, JANGAN raise

**Error handling:**
```python
# BENAR — defensive, tidak crash pipeline
try:
    df = scrape_broksum(ticker, date)
    if df.empty:
        logger.warning(f"No broksum data for {ticker} on {date}")
        return None
except requests.Timeout:
    logger.error(f"Timeout scraping broksum {ticker}: retry later")
    return None

# SALAH — crash seluruh pipeline karena satu emiten
df = scrape_broksum(ticker, date)  # bisa raise!
```

---

## Environment Variables

Semua secrets di `.env` (tidak di-commit). Lihat `.env.example`:

```
SUPABASE_URL=
SUPABASE_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Di GitHub Actions: simpan sebagai Repository Secrets.
Di kode: akses via `config/settings.py`, JANGAN import langsung di modul lain.

---

## Commands Penting

```bash
# Install dependencies
pip install -r requirements.txt

# Jalankan pipeline manual (development)
python main.py --mode eod --date today

# Download OHLCV historis (one-time)
python scripts/backfill_ohlcv.py --universe idx300 --years 5

# Health check semua services
python scripts/health_check.py

# Jalankan tests
pytest tests/ -v

# Jalankan dashboard lokal
streamlit run dashboard/app.py
```

---

## Aturan Penting

1. **JANGAN scrape saat jam pasar buka** (09.00–16.15 WIB) kecuali memang diperlukan
2. **Rate limiting WAJIB** di semua scraper — minimum 1 detik antara request
3. **Setiap scraper WAJIB punya retry logic** dengan exponential backoff (max 3 retry)
4. **Data broksum adalah yang paling berharga** — kalau ada conflict prioritas, broksum selalu duluan
5. **Jangan modifikasi `config/universe/*.csv` secara programatik** kecuali script `seed_universe.py`
6. **Setiap sinyal yang dikirim ke Telegram HARUS ada evidence** — tidak boleh bare score saja

---

## Fase Development

Lihat `docs/PHASES.md` untuk detail lengkap. Ringkasan:
- **Fase 1**: Pipeline data + Telegram alert EOD (SEKARANG)
- **Fase 2**: Broksum scraper + scoring engine
- **Fase 3**: News sentiment + Streamlit dashboard
- **Fase 4**: Wyckoff + Gorengan Radar + IPO Scanner
- **Fase 5**: Automation penuh di cloud

Saat ini di: **Fase 1**

Jika tidak yakin suatu fitur masuk fase berapa, tanya sebelum implement.
