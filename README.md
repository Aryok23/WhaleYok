# 🐋 WhaleDet IDX

> Sistem deteksi aktivitas institusional & smart money di Bursa Efek Indonesia (IDX).

Mendeteksi **akumulasi/distribusi whale** sebelum harga bergerak signifikan,
lalu kirim alert ke Telegram dan tampilkan di web dashboard.

---

## Cara Kerja

Setiap hari kerja jam 16.30 WIB, sistem otomatis:

1. **Fetch** OHLCV semua ~900 emiten IDX via yfinance
2. **Scrape** broker summary dan foreign flow
3. **Score** setiap emiten berdasarkan anomali volume, broker positioning, dan foreign flow
4. **Kirim** top sinyal ke Telegram
5. **Simpan** semua data ke database untuk analisis historis

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/USERNAME/whaledet-idx.git
cd whaledet-idx
pip install -r requirements.txt
```

### 2. Setup Environment

```bash
cp .env.example .env
# Edit .env dengan credentials kamu
```

### 3. Setup Database

```bash
# Jalankan migration di Supabase SQL Editor
# File: scripts/migrations/001_initial_schema.sql
```

### 4. Populate Data

```bash
# Seed daftar emiten
python scripts/seed_universe.py

# Download historis OHLCV (satu kali)
python scripts/backfill_ohlcv.py --universe idx300 --years 3
```

### 5. Test Run

```bash
python scripts/health_check.py
python main.py --dry-run --debug
```

---

## Stack

| Komponen | Tool |
|----------|------|
| Scheduler | GitHub Actions (cron) |
| Data OHLCV | yfinance |
| Data Broksum | IDX.co.id scraping |
| Database | Supabase (PostgreSQL) |
| Alert | Telegram Bot |
| Dashboard | Streamlit Cloud |
| Language | Python 3.11+ |

---

## Development Phases

- **Fase 1** ✅ Pipeline data + EOD alert
- **Fase 2** 🔄 Broker summary engine + composite scoring
- **Fase 3** ⏳ News sentiment + Streamlit dashboard
- **Fase 4** ⏳ Wyckoff + Gorengan radar + IPO scanner
- **Fase 5** ⏳ Production hardening

Detail: [docs/PHASES.md](docs/PHASES.md)

---

## Dokumentasi

| Dokumen | Deskripsi |
|---------|-----------|
| [CLAUDE.md](CLAUDE.md) | Project constitution untuk Claude Code |
| [docs/PHASES.md](docs/PHASES.md) | Roadmap development |
| [docs/SIGNAL_LOGIC.md](docs/SIGNAL_LOGIC.md) | Algoritma sinyal |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Schema database |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Cara deploy |

---

## Disclaimer

Sistem ini adalah **alat bantu analisis**, bukan rekomendasi investasi.
Semua keputusan trading adalah tanggung jawab masing-masing.
Selalu lakukan DYOR (Do Your Own Research) sebelum mengambil posisi.

---

## License

Private project — tidak untuk didistribusikan.
