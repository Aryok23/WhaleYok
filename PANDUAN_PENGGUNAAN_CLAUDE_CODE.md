# Panduan: Cara Pakai Claude Code untuk WhaleDet IDX

> Baca ini sebelum mulai development. Menghemat banyak waktu.

---

## Setup Awal (Satu Kali)

### 1. Install Claude Code
```bash
npm install -g @anthropic-ai/claude-code
```

### 2. Masuk ke direktori project
```bash
cd whaledet-idx
claude  # mulai sesi baru
```

### 3. Verifikasi CLAUDE.md terbaca
Di awal sesi, Claude Code otomatis baca CLAUDE.md.
Ketik ini untuk memastikan:
```
Baca CLAUDE.md dan ringkaskan pemahaman kamu tentang project ini.
```

---

## Cara Kerja yang Direkomendasikan

### Pola "Satu Sesi = Satu Task"
Jangan coba bangun semua sekaligus dalam satu sesi.
Setiap sesi fokus ke satu task spesifik.

**Baik:**
```
"Buat data/scrapers/ohlcv.py dengan fungsi fetch_ohlcv_daily"
```

**Kurang baik:**
```
"Buat semua scraper, engine, dan dashboard sekaligus"
```

### Pola Verifikasi Sebelum Lanjut
Setelah setiap file dibuat:
```
Jalankan [test command] dan tunjukkan outputnya.
Jangan lanjut sampai ini berjalan tanpa error.
```

### Pola Context Reset
Saat sesi sudah panjang (> 1-2 jam coding):
```
/clear
```
Lalu mulai sesi baru dengan menyebut konteks:
```
Kita sedang di Fase 1 WhaleDet IDX. Sudah selesai: 
ohlcv.py, features.py. Belum selesai: scorer.py.
Sekarang buat scorer.py.
```

---

## Prompt Templates yang Berguna

### Untuk Membuat File Baru
```
Buat [nama_file.py] dengan fungsi berikut:
- [nama_fungsi_1]: [deskripsi singkat]
- [nama_fungsi_2]: [deskripsi singkat]

Ikuti konvensi kode di CLAUDE.md.
Include type hints, docstrings, dan error handling yang proper.
Setelah selesai, jalankan python -c "import [module]; print('OK')" untuk verifikasi.
```

### Untuk Debugging
```
Ada error berikut:
[PASTE ERROR]

Analisis root cause. Jangan ubah logika yang tidak terkait.
Fix minimal yang menyelesaikan error ini.
```

### Untuk Review Kode
```
Review [nama_file.py] dan cek:
1. Apakah ada potential error yang belum di-handle?
2. Apakah rate limiting sudah ada di scraper?
3. Apakah type hints sudah lengkap?
4. Apakah ada hardcoded value yang seharusnya dari config?
```

### Untuk Testing
```
Buat tests/test_[module].py untuk [nama_file.py].
Test yang perlu ada:
- Happy path: input normal, output expected
- Edge case: empty input, None values
- Error case: API timeout, invalid data

Gunakan fixtures dari tests/fixtures/ jika tersedia.
```

### Untuk Refactoring (setelah fase selesai)
```
Fase [N] sudah selesai dan stabil.
Lakukan refactoring untuk:
- Eliminate duplicate code antara [file_a] dan [file_b]
- Tambahkan logging yang lebih informatif di [komponen]
- Improve error messages

JANGAN ubah public API (nama fungsi, parameter, return type).
JANGAN ubah logika bisnis.
Hanya internal implementation.
```

---

## Jangan Lakukan Ini

### ❌ Jangan Minta Semua Sekaligus
```
# JANGAN
"Buat semua file untuk Fase 1 sekaligus"

# LEBIH BAIK
"Buat settings.py dulu, lalu kita lanjut ke file berikutnya"
```

### ❌ Jangan Lupa Verifikasi
```
# JANGAN langsung lanjut setelah file dibuat
# SELALU verifikasi dulu:
"Jalankan python scripts/health_check.py dan tunjukkan outputnya"
```

### ❌ Jangan Biarkan Hardcoded Values
```
# JANGAN biarkan ini lolos:
API_KEY = "abc123"  # hardcoded!

# Selalu flag dan minta fix:
"Ada hardcoded API key di baris 15. Pindahkan ke config/settings.py"
```

### ❌ Jangan Skip Error Handling
```
# Kalau lihat ini di scraper:
response = requests.get(url)
data = response.json()

# Minta diperbaiki:
"Tambahkan error handling untuk network timeout dan invalid JSON"
```

---

## Troubleshooting Umum

### Claude Code Lupa Konteks
Gejala: Mulai buat file dengan konvensi yang berbeda dari sebelumnya.
Fix:
```
Baca ulang CLAUDE.md. Kita sedang di [fase]. 
Ikuti konvensi yang sudah ada di [file yang sudah benar].
```

### Claude Code Terlalu Agresif (ubah terlalu banyak)
Gejala: Diminta buat 1 fungsi, tapi Claude ubah 5 file.
Fix:
```
Stop. Undo semua perubahan. 
Buat HANYA [fungsi spesifik] di [file spesifik].
Jangan ubah file lain.
```

### Output Terlalu Panjang / Context Penuh
Gejala: Respons mulai tidak koheren atau lupa instruksi sebelumnya.
Fix:
```
/compact Focus on: files modified so far, current task, pending items
```

### Scraper Tiba-tiba Gagal
Gejala: Scraper yang tadinya jalan kini return empty.
Fix:
```
Website target mungkin berubah struktur.
Cek raw HTML yang tersimpan di logs/broksum_raw/ 
dan analisis apakah selector perlu diupdate.
```

---

## Checkpoint Harian

Sebelum tutup sesi development, jalankan:
```
Ringkaskan:
1. File apa yang dibuat/diubah hari ini?
2. Apa yang sudah berjalan dengan benar?
3. Apa yang masih pending atau bermasalah?
4. Langkah berikutnya adalah?

Simpan ringkasan ini ke docs/PROGRESS.md
```

Ini membuat sesi berikutnya bisa langsung lanjut dari mana kita berhenti.
