# WhaleDet IDX — Signal Logic Documentation

> Dokumen ini adalah source of truth untuk semua logika sinyal.
> Update dokumen ini SETIAP KALI ada perubahan algoritma.

---

## Filosofi Dasar

Sistem ini BUKAN prediksi harga. Sistem ini adalah **whale footprint detector**:
mencari jejak aktivitas institusional yang mereka tinggalkan di market.

Paus tidak bisa menyembunyikan jejaknya sepenuhnya karena modalnya terlalu besar.
Yang bisa kita deteksi adalah anomali yang terjadi SEBELUM harga bergerak signifikan.

---

## Universe Emiten

### Tiga Tier Scanning

| Tier | Universe | Jumlah | Sinyal | Data |
|------|----------|--------|--------|------|
| A | IDX80 | ~80 | Full composite | OHLCV + Broksum + Foreign |
| B | IDX300 minus IDX80 | ~220 | Medium | OHLCV + Broksum (partial) |
| C | Semua minus IDX300 | ~600 | Radar only | OHLCV saja |

### Kategori Khusus (treatment berbeda)
- **IPO < 90 hari**: Tidak ada baseline → pakai absolute threshold
- **Saham Konglo**: Cross-correlation dengan saudara dalam grup
- **Papan Pemantauan Khusus**: Flag otomatis, tambah disclaimer

---

## Layer 1: Volume Anomaly (semua tier)

### Z-Score Rolling Window

```python
z_score = (volume_today - rolling_mean_N) / rolling_std_N

# Window yang digunakan:
# - Tier A & B: N=20 hari (standar institusional)
# - Tier C (gorengan): N=60 hari (lebih stabil untuk saham sepi)
```

### Interpretasi Z-Score

| Z-Score | Interpretasi | Action |
|---------|-------------|--------|
| < 1.0 | Normal | Ignore |
| 1.0 – 2.0 | Slightly elevated | Monitor |
| 2.0 – 3.0 | Anomali sedang | Flag |
| 3.0 – 5.0 | Anomali kuat | Alert |
| > 5.0 | Ekstrem (event-driven?) | Alert + manual check |

### Volume-Price Relationship

```
Skenario A: Volume ↑↑ + Harga flat/turun sedikit = AKUMULASI (bullish)
Skenario B: Volume ↑↑ + Harga naik             = BREAKOUT (konfirmasi)
Skenario C: Volume ↑↑ + Harga turun             = DISTRIBUSI atau PANIC
Skenario D: Volume ↑↑ + Harga naik besar        = LATE STAGE (hati-hati)
```

---

## Layer 2: Broker Summary Analysis (Tier A & B)

### Broker Classification

```python
BROKER_CATEGORIES = {
    "foreign_institutional": {
        "codes": ["DB", "CS", "CLSA", "JPM", "MS", "UBS",
                  "CIMB", "RBS", "MACQ", "MERR", "NOMURA"],
        "weight": 1.5,
        "signal_power": "strongest"
    },
    "local_institutional": {
        "codes": ["BNI", "MNC", "TRIM", "MAND", "BCA"],
        "weight": 1.0,
        "signal_power": "medium"
    },
    "retail_heavy": {
        "codes": ["NI", "YP", "OD", "CP", "ZP", "XA"],
        "weight": 0.2,
        "signal_power": "weak/noise"
    }
}
```

### Broker Score Calculation

```python
def compute_broker_score(broksum_df):
    """
    Score 0-100 berdasarkan aktivitas broker institusional.
    
    Bullish signals:
    - Foreign institutional NET BUY
    - Broker concentration tinggi (1-2 broker dominan)
    - Nilai per transaksi besar (non-retail)
    
    Bearish signals:
    - Foreign institutional NET SELL setelah streak beli
    - Retail dominan di sisi beli (distribusi ke retail)
    """
    score = 0
    
    # Foreign institutional net position
    foreign_net = get_net_by_category(broksum_df, "foreign_institutional")
    if foreign_net > 0:
        score += min(40, foreign_net / BASELINE_FOREIGN * 40)
    
    # Broker concentration (Herfindahl-like)
    top2_share = get_top2_broker_share(broksum_df)
    if top2_share > 0.6:
        score += 20
    elif top2_share > 0.4:
        score += 10
    
    # Average transaction value (retail vs institutional)
    avg_txn = total_value / total_frequency
    if avg_txn > 500_000_000:  # > 500 juta per transaksi = institusional
        score += 20
    elif avg_txn > 100_000_000:
        score += 10
    
    # Streak: berapa hari berturut-turut foreign institutional net buy?
    streak = get_foreign_buy_streak(ticker, lookback=10)
    score += min(20, streak * 4)
    
    return min(100, score)
```

### Pattern Recognition

```
AKUMULASI BULLISH (beli signal):
✓ Foreign institutional di KIRI (net buy)
✓ Retail di KANAN (jual ke retail — bandar unload ke retail = distribusi,
  tapi kalau RETAIL yang jual ke ASING = justru bullish)
✓ Nilai per transaksi besar
✓ Streak ≥ 3 hari

DISTRIBUSI WARNING (jual/hati-hati):
✗ Foreign institutional pindah ke KANAN setelah streak KIRI
✗ Retail masuk besar-besaran ke KIRI
✗ Volume spike tapi harga tidak naik (absorption sudah selesai)
```

---

## Layer 3: Foreign Flow (Tier A)

### Foreign Divergence Signal

```python
# Signal paling kuat di IDX secara historis (paper Rudiawarni 2024):
# Harga turun TAPI asing tetap beli = bullish divergence

foreign_divergence = (
    price_return_5d < -0.02 AND    # harga turun > 2% dalam 5 hari
    foreign_net_5d > 0              # tapi asing net beli
)
# Win rate historis divergence signal di IDX: cukup tinggi
```

### Foreign Score

```python
def compute_foreign_score(foreign_df):
    score = 0
    
    # Net flow hari ini
    if foreign_net_today > 0:
        score += 20
    
    # Streak akumulasi (5 hari, 10 hari, 20 hari)
    streak_5d = foreign_net_5d > 0
    streak_10d = foreign_net_10d > 0
    streak_20d = foreign_net_20d > 0
    
    if streak_5d: score += 15
    if streak_10d: score += 20
    if streak_20d: score += 25
    
    # Divergence bonus (paling kuat)
    if foreign_divergence:
        score += 20
    
    return min(100, score)
```

---

## Layer 4: Wyckoff Phase Detection (Fase 4)

### Phase Classifier

```
Phase A — SELLING CLIMAX:
  - Volume z-score > 3.5 dengan candle bearish besar
  - Harga turun > 5% dalam 3 hari
  - Kemudian bounce (automatic rally)

Phase B — TRADING RANGE:
  - Harga sideways (range < 10% selama ≥ 10 hari)
  - Volume di atas rata-rata tapi tidak ekstrem (1.3x-2x)
  - Multiple test of support/resistance

Phase C — SPRING:
  - False breakdown di bawah support dengan VOLUME RENDAH
  - Harga tutup kembali di atas support dalam 1-2 hari
  - Volume z-score < 0 saat breakdown (key tell!)

Phase D — SIGN OF STRENGTH:
  - Volume tinggi (z-score > 2)
  - Candle bullish besar, tutup near high
  - Breakout di atas resistance trading range

Phase E — MARKUP:
  - Trend naik konfirmasi
  - Volume healthy (tidak harus ekstrem)
```

---

## Layer 5: Gorengan Radar (Fase 4)

### Phase Classification untuk Lapis 3

```
SEPI       : volume_ratio_60d < 2      → Ignore
AKUMULASI  : 2 ≤ ratio < 10, harga flat → WATCH (entry ideal)
PRE_PUMP   : 10 ≤ ratio < 50           → Masih bisa entry, risiko naik
PUMP       : ratio ≥ 50 ATAU naik >20% → TERLAMBAT — jangan masuk
LATE_STAGE : harga sudah naik >50% dari 20d low → EXIT warning
```

### Guardrails Wajib di Alert

Setiap sinyal Tier C (gorengan/lapis 3) WAJIB sertakan:
- "⚠️ Saham lapis 3 — risiko sangat tinggi"
- "Max posisi: 3-5% portofolio"
- "Exit plan WAJIB sebelum masuk"
- Persentase kenaikan dari recent low

---

## Composite Scoring Engine

### Bobot per Layer

```python
WEIGHTS = {
    "fase_1": {
        "volume": 1.0,  # hanya volume di fase 1
    },
    "fase_2": {
        "volume":  0.30,
        "broker":  0.40,  # paling penting untuk IDX
        "foreign": 0.30,
    },
    "fase_3_plus": {
        "volume":  0.25,
        "broker":  0.35,
        "foreign": 0.25,
        "news":    0.15,
    }
}
```

### Signal Types

| Score | Signal Type | Action |
|-------|-------------|--------|
| ≥ 85 | STRONG_BUY | Alert kuat, prioritas tinggi |
| 70 – 84 | WATCH_BUY | Alert, konfirmasi besok |
| 50 – 69 | MONITOR | Masuk watchlist |
| 30 – 49 | NEUTRAL | Tidak ada aksi |
| < 30 | DISTRIBUSI | Warning (jika sebelumnya tinggi) |

---

## Format Alert Telegram

### Format Standard

```
🐋 WhaleDet IDX — {tanggal} {jam}

🟢 TOP SIGNALS HARI INI:

1. {TICKER} | Score {N} | {SIGNAL_TYPE}
   📊 Vol: {N}x baseline | {N} hari berturut
   🏦 Broker: {broker_names} di kiri
   💱 Foreign: net +Rp {N}M ({N} hari streak)
   📰 {news_headline jika ada}
   → {ACTION_LABEL}

[... dst ...]

⚠️ Disclaimer: Ini bukan rekomendasi investasi.
DYOR sebelum mengambil posisi.

📊 Detail: {dashboard_url}
```

### Format Gorengan (Tier C)

```
🔍 RADAR LAPIS 3: {TICKER}
Phase: {PHASE} | Vol: {N}x (60d)
Harga: +{N}% dari recent low

⚠️ RISIKO TINGGI — Bukan sinyal beli.
Ini early warning saja. DYOR wajib.
```

---

## Data Quality Rules

Sinyal TIDAK dikirim jika:
- Volume data missing atau 0
- Harga penutupan = 0 atau NaN
- Emiten di-suspend oleh BEI
- Emiten di Papan Pemantauan Khusus (flag dulu, kirim dengan disclaimer)
- Data broksum tidak tersedia lebih dari 3 hari berturut-turut (degraded mode)
