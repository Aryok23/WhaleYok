# WhaleDet IDX — Deployment Guide

---

## Prerequisites

Sebelum deploy, pastikan sudah punya:
- [ ] GitHub account
- [ ] Supabase account (free) — https://supabase.com
- [ ] Telegram account + buat bot via @BotFather

---

## Step 1: Setup Supabase

### 1.1 Buat Project Baru
1. Login ke https://supabase.com/dashboard
2. "New Project" → isi nama "whaledet-idx"
3. Set password database yang kuat
4. Region: Singapore (ap-southeast-1) — paling dekat Indonesia
5. Tunggu provisioning (~2 menit)

### 1.2 Buat Tables
Di Supabase Dashboard → SQL Editor, jalankan:

```sql
-- Jalankan file ini: scripts/migrations/001_initial_schema.sql
-- (akan dibuat di Fase 1)
```

### 1.3 Ambil Credentials
Di Settings → API:
- `SUPABASE_URL` = Project URL (format: https://xxxx.supabase.co)
- `SUPABASE_KEY` = anon/public key (bukan service_role!)

---

## Step 2: Setup Telegram Bot

### 2.1 Buat Bot
1. Buka Telegram, cari @BotFather
2. Kirim `/newbot`
3. Ikuti instruksi, dapatkan **Bot Token**

### 2.2 Dapatkan Chat ID
1. Kirim pesan apapun ke bot baru kamu
2. Buka: `https://api.telegram.org/bot{TOKEN}/getUpdates`
3. Cari `"chat":{"id": XXXXXX}` — itu `TELEGRAM_CHAT_ID` kamu

---

## Step 3: Setup GitHub Repository

### 3.1 Buat Repo
```bash
git init
git remote add origin https://github.com/USERNAME/whaledet-idx.git
```

### 3.2 Setup Secrets
Di GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret Name | Value |
|-------------|-------|
| `SUPABASE_URL` | URL dari Supabase |
| `SUPABASE_KEY` | Anon key dari Supabase |
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID kamu |

### 3.3 File .env.example (commit ini)
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
TELEGRAM_BOT_TOKEN=your-bot-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
```

### 3.4 File .gitignore (commit ini)
```
.env
*.pyc
__pycache__/
.DS_Store
logs/
*.log
```

---

## Step 4: GitHub Actions Workflow

File `.github/workflows/daily_scan.yml`:

```yaml
name: WhaleDet Daily Scan

on:
  schedule:
    # 09:30 UTC = 16:30 WIB (UTC+7)
    # Senin-Jumat saja
    - cron: '30 9 * * 1-5'
  workflow_dispatch:  # bisa trigger manual dari GitHub UI

jobs:
  daily-scan:
    runs-on: ubuntu-latest
    timeout-minutes: 30  # safety net

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run health check
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python scripts/health_check.py

      - name: Run daily scan
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python main.py --mode eod

      - name: Notify on failure
        if: failure()
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python -c "
          import os, requests
          token = os.environ['TELEGRAM_BOT_TOKEN']
          chat_id = os.environ['TELEGRAM_CHAT_ID']
          requests.post(
              f'https://api.telegram.org/bot{token}/sendMessage',
              json={'chat_id': chat_id, 'text': '⚠️ WhaleDet pipeline GAGAL hari ini. Cek GitHub Actions.'}
          )
          "
```

**Catatan**: Repo harus PUBLIC agar GitHub Actions gratis unlimited.
Kalau mau private, tetap bisa tapi ada limit 2.000 menit/bulan (masih cukup).

---

## Step 5: Deploy Streamlit Dashboard (Fase 3+)

### 5.1 Siapkan requirements.txt
Pastikan `streamlit` ada di requirements.txt.

### 5.2 Deploy ke Streamlit Community Cloud
1. Buka https://share.streamlit.io
2. Login dengan GitHub
3. "New app" → pilih repo `whaledet-idx`
4. Main file path: `dashboard/app.py`
5. Advanced settings → Secrets (isi env vars yang sama)

### 5.3 Keep Alive (opsional)
Streamlit sleep setelah 12 jam tidak ada traffic.
Untuk personal use, ini tidak masalah — cukup kunjungi sekali sehari.

Kalau mau otomatis tetap hidup:
```python
# Di dashboard/app.py, tambahkan auto-refresh
import time
import streamlit as st
st.markdown("""
<meta http-equiv="refresh" content="3600">
""", unsafe_allow_html=True)
```

---

## Step 6: One-Time Setup (jalankan sekali)

```bash
# 1. Seed universe emiten
python scripts/seed_universe.py

# 2. Backfill OHLCV historis 5 tahun untuk IDX300
# Perlu waktu ~20-30 menit, jalankan sekali saja
python scripts/backfill_ohlcv.py --universe idx300 --years 5

# 3. Verifikasi data masuk ke Supabase
python scripts/health_check.py --verbose
```

---

## Monitoring

### Cek Pipeline Sukses
- GitHub Actions → tab "Actions" di repo → cek run terbaru
- Supabase → Table Editor → `signals` → cek ada data hari ini
- Telegram → cek pesan masuk ~16.30 WIB

### Jika Pipeline Gagal
1. Cek GitHub Actions log untuk error spesifik
2. Jalankan lokal: `python main.py --mode eod --debug`
3. Cek Supabase quota (Settings → Usage)
4. Cek apakah ada perubahan struktur website yang di-scrape

### Supabase Pause Recovery
Jika Supabase project ter-pause (karena inaktif > 7 hari):
1. Login ke https://supabase.com/dashboard
2. Klik "Restore" pada project yang pause
3. Tunggu ~2 menit

Ini tidak akan terjadi jika pipeline jalan setiap hari.
