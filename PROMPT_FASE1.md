# PROMPT FASE 1 — Pipeline Data + EOD Alert

> Berikan prompt ini ke Claude Code untuk membangun Fase 1.
> Jalankan di root direktori project setelah CLAUDE.md ada.

---

## PROMPT UTAMA (copy-paste ke Claude Code)

```
Kita akan membangun Fase 1 dari WhaleDet IDX sesuai CLAUDE.md dan docs/PHASES.md.

Baca CLAUDE.md, docs/PHASES.md, docs/DATA_DICTIONARY.md, dan docs/DEPLOYMENT.md
terlebih dahulu sebelum mulai menulis kode apapun.

## Goal Fase 1
Script Python yang:
1. Jalan otomatis via GitHub Actions setiap hari kerja jam 16.30 WIB
2. Fetch OHLCV semua emiten IDX via yfinance
3. Hitung z-score volume (rolling 20 hari)
4. Kirim top 10 sinyal ke Telegram
5. Simpan semua data ke Supabase

## Yang Harus Dibuat (urutan prioritas):

### Step 1: Foundation
Buat file-file ini terlebih dahulu:
- `config/settings.py` — load semua env vars dengan validasi
- `.env.example` — template tanpa nilai asli
- `.gitignore` — pastikan .env tidak ter-commit
- `requirements.txt` — dengan versi pinned

Dependencies yang dibutuhkan:
- yfinance>=0.2.40
- pandas>=2.0.0
- numpy>=1.24.0
- supabase>=2.0.0
- python-telegram-bot>=20.0
- requests>=2.31.0
- python-dotenv>=1.0.0
- scikit-learn>=1.3.0  (untuk Isolation Forest di fase 2)

### Step 2: Database Migration
Buat `scripts/migrations/001_initial_schema.sql`:
- Tabel sesuai DATA_DICTIONARY.md
- Index yang direkomendasikan
- RLS disabled (private project, tidak butuh row-level security)

### Step 3: Universe Seeder
Buat `scripts/seed_universe.py`:
- Fetch daftar semiten dari IDX API atau yfinance
- Populate tabel `emiten_universe` di Supabase
- Tandai is_lq45, is_idx80, is_idx300
- Log progress setiap 50 emiten

Ticker format untuk yfinance IDX: tambahkan suffix ".JK"
Contoh: BBCA.JK, TLKM.JK, GOTO.JK

Sumber daftar emiten IDX:
- https://www.idx.co.id/umum/perusahaan-tercatat/profil-perusahaan-tercatat/
- Atau gunakan yfinance: yf.Ticker("^JKSE") untuk IHSG

### Step 4: OHLCV Scraper
Buat `data/scrapers/ohlcv.py`:
- Fungsi `fetch_ohlcv_daily(tickers: list, date: str) -> pd.DataFrame`
- Fungsi `fetch_ohlcv_batch(tickers: list, start: str, end: str) -> pd.DataFrame`
- Rate limiting: jangan fetch > 50 ticker sekaligus
- Retry logic: exponential backoff, max 3 retry
- Return empty DataFrame (bukan raise) jika ticker tidak tersedia

### Step 5: Feature Engine (v1)
Buat `engine/features.py`:
- Fungsi `compute_volume_zscore(df: pd.DataFrame, window: int = 20) -> pd.Series`
- Fungsi `compute_price_change(df: pd.DataFrame, periods: list = [1, 3, 5]) -> pd.DataFrame`
- Fungsi `classify_volume_price_scenario(zscore: float, price_change: float) -> str`
  Returns: "ACCUMULATION", "BREAKOUT", "DISTRIBUTION", "PANIC", "NORMAL"

### Step 6: Scorer (v1)
Buat `engine/scorer.py`:
- Fungsi `score_emiten_v1(features: dict) -> dict`
  Input: volume_zscore, price_change_1d, price_change_5d
  Output: {score: float, signal_type: str, evidence: dict}
- Fase 1 hanya pakai volume score (100% weight)

Logika score volume:
- zscore < 1: score = 0
- zscore 1-2: score = 20-40
- zscore 2-3: score = 40-65
- zscore 3-4: score = 65-80
- zscore > 4: score = 80-95
- Bonus +5 jika harga naik hari ini
- Penalty -10 jika volume naik tapi harga turun > 2%

### Step 7: Telegram Bot
Buat `output/telegram_bot.py`:
- Fungsi `send_eod_alert(signals: list) -> bool`
- Format pesan sesuai SIGNAL_LOGIC.md
- Handle error gracefully (jika Telegram down, log warning, jangan crash)
- Maximum 10 sinyal per pesan
- Jika > 10 sinyal, kirim pesan terpisah

### Step 8: Database Writer
Buat `output/db_writer.py`:
- Fungsi `write_price_data(df: pd.DataFrame) -> int` (return rows written)
- Fungsi `write_signals(signals: list) -> int`
- Upsert (bukan insert) untuk handle re-run di hari yang sama
- Batch insert: 100 rows per batch untuk efisiensi

### Step 9: Main Orchestrator
Buat `main.py`:
```
Alur:
1. Load config (validate semua env vars ada)
2. Load universe emiten dari Supabase
3. Fetch OHLCV hari ini untuk semua emiten
4. Load OHLCV historis dari Supabase (untuk z-score)
5. Compute features
6. Score semua emiten
7. Filter: ambil yang score > 50
8. Sort by score descending
9. Kirim top 10 ke Telegram
10. Simpan semua signals ke Supabase
11. Log ringkasan: berapa emiten diproses, berapa sinyal dihasilkan
```

Argumen CLI:
- `--mode eod` (default)
- `--date YYYY-MM-DD` (default: hari ini)
- `--debug` (lebih verbose logging)
- `--dry-run` (jangan kirim Telegram dan jangan write ke DB)

### Step 10: Health Check
Buat `scripts/health_check.py`:
- Cek koneksi Supabase (bisa query)
- Cek Telegram bot (bisa kirim pesan test)
- Cek yfinance (bisa fetch 1 ticker)
- Print summary: OK / FAIL per service

### Step 11: Backfill Script
Buat `scripts/backfill_ohlcv.py`:
- Download OHLCV historis untuk backfill
- Argumen: --universe [all|idx80|idx300], --years [1-10]
- Progress bar (tqdm)
- Skip ticker yang sudah ada di database
- Rate limiting ketat: 1 detik per ticker

### Step 12: GitHub Actions
Buat `.github/workflows/daily_scan.yml` sesuai DEPLOYMENT.md.

## Aturan Tambahan untuk Fase 1

1. SEMUA fungsi publik harus punya type hints
2. SEMUA fungsi non-trivial harus punya docstring
3. JANGAN hardcode ticker list — selalu load dari database atau CSV
4. Logging level: INFO untuk progress normal, WARNING untuk data issues, ERROR untuk failures
5. Setiap run harus idempotent (bisa diulang di hari yang sama tanpa duplikasi data)
6. Test bahwa pipeline berjalan dengan `python main.py --dry-run` sebelum deploy

## Urutan Pengerjaan yang Disarankan

Kerjakan dalam urutan ini karena ada dependency:
1. settings.py + requirements.txt (foundation)
2. 001_initial_schema.sql (database)
3. db_writer.py (perlu schema ada dulu)
4. ohlcv.py (data fetcher)
5. seed_universe.py (populate database)
6. features.py (compute dari data)
7. scorer.py (compute dari features)
8. telegram_bot.py (output)
9. main.py (orchestrate semua)
10. health_check.py + backfill_ohlcv.py (utilities)
11. daily_scan.yml (CI/CD)

Mulai dari mana saja yang masuk akal, tapi pastikan setiap file
bisa ditest secara independen sebelum lanjut ke file berikutnya.
```

---

## PROMPT LANJUTAN (setelah Fase 1 selesai, untuk testing)

```
Fase 1 selesai. Sekarang lakukan testing end-to-end:

1. Jalankan `python scripts/health_check.py` dan pastikan semua OK
2. Jalankan `python scripts/seed_universe.py` untuk populate emiten
3. Jalankan `python scripts/backfill_ohlcv.py --universe idx80 --years 1`
   untuk download 1 tahun data IDX80 (lebih cepat dari IDX300)
4. Jalankan `python main.py --dry-run --debug`
   dan tunjukkan output-nya
5. Fix semua error yang muncul
6. Setelah dry-run sukses, jalankan `python main.py --mode eod`
   dan konfirmasi alert masuk ke Telegram

Jika ada error di step manapun, debug dan fix sebelum lanjut.
```

---

## PROMPT DEBUGGING (jika ada masalah)

```
Ada error berikut saat menjalankan [command]:

[PASTE ERROR DISINI]

Analisis root cause-nya dan fix. Jangan ubah logika bisnis,
hanya fix bug yang menyebabkan error ini.

Setelah fix, jalankan kembali command yang sama dan konfirmasi
tidak ada error lagi.
```
