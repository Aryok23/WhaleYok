# WhaleDet IDX — Development Phases

## Status Saat Ini: FASE 1

---

## FASE 1 — Data Pipeline + EOD Alert
**Target: Berjalan di GitHub Actions dalam 1-2 minggu**

### Goal
Script jalan otomatis setiap hari kerja jam 16.30 WIB.
Kirim top 10 sinyal volume anomali ke Telegram.
Data tersimpan di Supabase.

### Deliverables
- [ ] GitHub repo setup + `.github/workflows/daily_scan.yml`
- [ ] Supabase: schema tabel `price_data`, `signals`, `emiten_universe`
- [ ] `scripts/seed_universe.py` — populate daftar semua emiten IDX
- [ ] `scripts/backfill_ohlcv.py` — download 5 tahun historis IDX300
- [ ] `data/scrapers/ohlcv.py` — daily OHLCV fetch via yfinance
- [ ] `engine/features.py` — z-score volume, price change, basic ratios
- [ ] `engine/scorer.py` (v1) — score berdasarkan volume anomali saja
- [ ] `output/telegram_bot.py` — format dan kirim alert
- [ ] `output/db_writer.py` — simpan ke Supabase
- [ ] `main.py` — entry point, orkestrasi semua komponen
- [ ] `scripts/health_check.py` — validasi semua koneksi

### Definition of Done
- Script jalan tanpa error di GitHub Actions
- Telegram menerima alert setiap hari kerja ~16.30 WIB
- Data tersimpan di Supabase (bisa diquery)
- Jika satu emiten gagal di-fetch, script tetap jalan untuk yang lain

### Sinyal Fase 1 (sederhana)
```
Volume z-score > 2.5 (rolling 20 hari)
+ Harga naik > 0% hari ini
→ Masuk kandidat

Sort by z-score, ambil top 10
Kirim ke Telegram dengan format sederhana
```

---

## FASE 2 — Broksum Engine + Composite Scoring
**Target: 2-4 minggu setelah Fase 1 stabil**

### Goal
Tambah broker summary dan foreign flow ke sinyal.
Composite score yang lebih intelligent.

### Deliverables
- [ ] Supabase: tambah tabel `broker_summary`, `foreign_flow`
- [ ] `data/scrapers/broksum.py` — scraper IDX/Pasardana broker summary
- [ ] `data/scrapers/foreign_flow.py` — scraper foreign net
- [ ] `config/broker_profiles.py` — klasifikasi broker (asing/lokal/retail)
- [ ] `engine/features.py` (v2) — broker concentration, foreign divergence
- [ ] `engine/scorer.py` (v2) — composite: volume (30%) + broker (40%) + foreign (30%)
- [ ] Telegram alert (v2) — tampilkan evidence broksum
- [ ] `tests/test_features.py` — unit tests untuk semua fitur baru

### Sinyal Fase 2
```
Composite Score = 
  0.30 × volume_score +
  0.40 × broker_score +
  0.30 × foreign_score

Score > 75  → WATCH BUY
Score > 85  → STRONG BUY
Score < 30  → DISTRIBUSI WARNING
```

### Catatan Penting Fase 2
Broksum scraper adalah komponen paling tricky:
- IDX website struktur bisa berubah → build scraper yang resilient
- Pasardana sebagai fallback jika IDX down
- Selalu simpan raw HTML response untuk debugging
- Rate limit: minimum 2 detik antara request

---

## FASE 3 — News Sentiment + Dashboard
**Target: 1-2 bulan setelah Fase 2**

### Goal
Tambah konteks berita ke sinyal.
Web dashboard untuk analisis mendalam.

### Deliverables
- [ ] Supabase: tambah tabel `news_items`
- [ ] `data/scrapers/news_rss.py` — RSS feed scraper (Kontan, Bisnis, IDX)
- [ ] `engine/news_sentiment.py` — keyword mapping + sentiment scoring
- [ ] `config/sector_keywords.py` — mapping keyword → sektor → emiten
- [ ] `dashboard/app.py` — Streamlit dashboard v1
  - Tabel sinyal semua emiten dengan filter
  - Chart candlestick + volume per emiten
  - Broksum visualization
  - News feed per emiten
- [ ] Deploy Streamlit ke Community Cloud
- [ ] Link di Telegram alert ke dashboard

### RSS Feeds yang Di-scrape
```python
FEEDS = [
    "https://www.kontan.co.id/rss/investasi",
    "https://market.bisnis.com/rss",
    "https://www.cnbcindonesia.com/market/rss",
    # IDX announcements (keterbukaan informasi)
    "https://www.idx.co.id/umum/berita-dan-pengumuman/pengumuman/",
]
```

---

## FASE 4 — Advanced Detection
**Target: 2-3 bulan setelah Fase 3**

### Goal
Wyckoff phase detection, gorengan radar, IPO/konglo scanner.

### Deliverables
- [ ] `engine/wyckoff.py` — Wyckoff phase classifier (A/B/C/D/E)
  - Selling Climax detection
  - Spring detection
  - Sign of Strength confirmation
- [ ] `engine/gorengan_radar.py` — low-cap anomaly detector
  - Volume burst ratio (baseline 60 hari)
  - Phase classification (SEPI/AKUMULASI/PRE_PUMP/PUMP/LATE)
  - Guardrail: flag kalau sudah naik > 50% dari low
- [ ] `engine/ipo_scanner.py` — IPO & konglo tracker
  - Auto-detect emiten IPO baru (< 90 hari listing)
  - Konglo group correlation alert
  - Corporate action monitor
- [ ] Backtesting framework sederhana
  - Historical signal replay
  - Win rate calculation per signal type
  - Max drawdown analysis
- [ ] Dashboard v2: tambah Wyckoff viz, gorengan phase indicator

---

## FASE 5 — Production Hardening
**Target: Setelah semua fase sebelumnya stabil**

### Goal
Sistem yang benar-benar production-grade.

### Deliverables
- [ ] Monitoring & alerting (Telegram kalau pipeline gagal)
- [ ] Data quality checks otomatis
- [ ] Auto-recovery jika Supabase pause (wakeuper script)
- [ ] Dokumentasi lengkap
- [ ] Optional: Pindah ke VPS Indonesia kalau butuh always-on dashboard

---

## Catatan Cross-Fase

### Apa yang TIDAK Akan Kita Bangun
- Intraday real-time (data tidak tersedia gratis + noise terlalu tinggi)
- Auto-trading (execute order otomatis — terlalu berisiko)
- Prediksi harga (bukan tujuan sistem ini)

### Prinsip Iterasi
1. Setiap fase harus **fully functional dan deployed** sebelum mulai fase berikutnya
2. Jangan refactor besar-besaran di tengah fase — catat di TODO, kerjakan di fase berikutnya
3. Test manual sebelum push ke GitHub Actions
4. Log semua anomali data ke file `logs/` untuk debugging

### Upgrade Path Database (jika 500MB tidak cukup)
```
Saat ini: Supabase Free (500MB)
  ↓ jika storage > 400MB
Opsi A: Supabase Pro $25/bulan (8GB) — paling mudah
Opsi B: Agregate data lama ke weekly, hapus daily > 2 tahun
Opsi C: Pindah ke VPS + self-hosted PostgreSQL
```
