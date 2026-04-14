# WhaleDet IDX — Data Dictionary

> Definisi semua kolom di database Supabase.
> Jadikan referensi saat menulis query atau migration.

---

## Tabel: `emiten_universe`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `ticker` | VARCHAR(10) PK | Kode saham IDX, uppercase, tanpa suffix `.JK` |
| `name` | VARCHAR(200) | Nama perusahaan lengkap |
| `sector` | VARCHAR(100) | Sektor BEI (e.g., "Basic Materials") |
| `sub_sector` | VARCHAR(100) | Sub-sektor |
| `papan` | VARCHAR(20) | "Utama", "Pengembangan", "Akselerasi", "Pemantauan" |
| `market_cap_tier` | VARCHAR(10) | "large", "mid", "small", "micro" |
| `is_lq45` | BOOLEAN | Masuk LQ45 saat ini |
| `is_idx80` | BOOLEAN | Masuk IDX80 saat ini |
| `is_idx300` | BOOLEAN | Masuk IDX300 saat ini |
| `konglo_group` | VARCHAR(50) | Nama grup konglomerasi (nullable) |
| `listing_date` | DATE | Tanggal listing di BEI |
| `is_ipo_new` | BOOLEAN | True jika listing < 90 hari |
| `last_updated` | TIMESTAMP | Kapan row ini terakhir diupdate |

---

## Tabel: `price_data`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `date` | DATE | Tanggal bursa (hari kerja) |
| `ticker` | VARCHAR(10) | Kode saham IDX |
| `open` | NUMERIC(12,2) | Harga pembukaan (IDR) |
| `high` | NUMERIC(12,2) | Harga tertinggi (IDR) |
| `low` | NUMERIC(12,2) | Harga terendah (IDR) |
| `close` | NUMERIC(12,2) | Harga penutupan (IDR) |
| `volume` | BIGINT | Volume dalam lembar saham |
| `turnover` | BIGINT | Nilai transaksi dalam IDR |
| `source` | VARCHAR(20) | "yfinance", "idx_direct" |

Primary key: `(date, ticker)`

---

## Tabel: `broker_summary`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `date` | DATE | Tanggal bursa |
| `ticker` | VARCHAR(10) | Kode saham IDX |
| `broker_code` | VARCHAR(10) | Kode broker (e.g., "DB", "CS", "YP") |
| `buy_value` | BIGINT | Total nilai beli dalam IDR |
| `sell_value` | BIGINT | Total nilai jual dalam IDR |
| `net_value` | BIGINT | buy_value - sell_value (positif = net buy) |
| `buy_volume` | BIGINT | Total lembar dibeli |
| `sell_volume` | BIGINT | Total lembar dijual |
| `buy_freq` | INTEGER | Frekuensi transaksi beli |
| `sell_freq` | INTEGER | Frekuensi transaksi jual |
| `broker_category` | VARCHAR(30) | "foreign_institutional", "local_institutional", "retail_heavy" |
| `avg_buy_txn_value` | BIGINT | buy_value / buy_freq (rata-rata per transaksi) |

Primary key: `(date, ticker, broker_code)`

**Catatan penting**: Data broksum mulai tersedia sejak hari pertama scraper jalan.
Tidak ada historis yang bisa diambil retroaktif. Semakin cepat mulai, semakin baik.

---

## Tabel: `foreign_flow`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `date` | DATE | Tanggal bursa |
| `ticker` | VARCHAR(10) | Kode saham IDX |
| `foreign_buy` | BIGINT | Total nilai beli asing dalam IDR |
| `foreign_sell` | BIGINT | Total nilai jual asing dalam IDR |
| `foreign_net` | BIGINT | foreign_buy - foreign_sell |
| `foreign_net_5d` | BIGINT | Kumulatif 5 hari (computed) |
| `foreign_net_10d` | BIGINT | Kumulatif 10 hari (computed) |
| `foreign_net_20d` | BIGINT | Kumulatif 20 hari (computed) |
| `foreign_buy_streak` | INTEGER | Berapa hari berturut net buy (computed) |
| `foreign_divergence` | BOOLEAN | True jika price_5d < -2% tapi net_5d > 0 |

Primary key: `(date, ticker)`

---

## Tabel: `signals`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `id` | SERIAL PK | Auto-increment |
| `date` | DATE | Tanggal sinyal dihasilkan |
| `ticker` | VARCHAR(10) | Kode saham IDX |
| `composite_score` | NUMERIC(5,2) | Skor gabungan 0-100 |
| `signal_type` | VARCHAR(20) | "STRONG_BUY", "WATCH_BUY", "MONITOR", "DISTRIBUSI" |
| `phase` | VARCHAR(30) | "ACCUMULATION", "PRE_PUMP", "WYCKOFF_B", dll |
| `tier` | VARCHAR(5) | "A", "B", "C" (universe tier) |
| `volume_zscore` | NUMERIC(6,2) | Z-score volume hari ini |
| `volume_score` | NUMERIC(5,2) | Komponen skor volume (0-100) |
| `broker_score` | NUMERIC(5,2) | Komponen skor broksum (0-100, null di fase 1) |
| `foreign_score` | NUMERIC(5,2) | Komponen skor foreign flow (0-100, null di fase 1) |
| `news_score` | NUMERIC(5,2) | Komponen skor sentimen berita (0-100, null di fase 1-2) |
| `evidence_json` | JSONB | Detail evidence yang mendukung sinyal |
| `sent_to_telegram` | BOOLEAN | Apakah sudah dikirim ke Telegram |
| `created_at` | TIMESTAMP | Kapan sinyal dibuat |

**evidence_json structure:**
```json
{
  "volume": {
    "today": 5000000,
    "baseline_20d": 1200000,
    "ratio": 4.17,
    "zscore": 3.2
  },
  "broker": {
    "top_buyers": [
      {"code": "DB", "net_value": 45000000000, "category": "foreign_institutional"},
      {"code": "CS", "net_value": 23000000000, "category": "foreign_institutional"}
    ],
    "top2_concentration": 0.72,
    "avg_txn_value": 750000000
  },
  "foreign": {
    "net_today": 12000000000,
    "net_5d": 45000000000,
    "streak_days": 7,
    "divergence": false
  },
  "news": [
    {"headline": "Pemerintah percepat B50...", "sentiment": 0.8, "source": "kontan.co.id"}
  ]
}
```

---

## Tabel: `news_items`

| Kolom | Tipe | Deskripsi |
|-------|------|-----------|
| `id` | SERIAL PK | Auto-increment |
| `date` | DATE | Tanggal berita |
| `tickers` | VARCHAR[] | Array ticker yang terkena dampak |
| `sectors` | VARCHAR[] | Array sektor yang terkena dampak |
| `headline` | TEXT | Judul berita |
| `summary` | TEXT | Ringkasan (nullable) |
| `source` | VARCHAR(100) | Domain sumber (e.g., "kontan.co.id") |
| `source_weight` | NUMERIC(3,2) | Bobot kredibilitas sumber (0.0 - 1.0) |
| `sentiment_score` | NUMERIC(3,2) | -1.0 (sangat negatif) sampai +1.0 (sangat positif) |
| `url` | TEXT | URL berita |
| `created_at` | TIMESTAMP | Kapan diambil |

---

## Computed Fields (tidak di-store, dihitung saat query)

Beberapa field di-compute saat dibutuhkan untuk menghemat storage:
- `volume_zscore`: dihitung dari `price_data` rolling 20 hari
- `foreign_net_Nd`: dihitung dari kumulatif `foreign_flow`
- `broker_concentration`: dihitung dari distribusi `broker_summary`

---

## Index Rekomendasi

```sql
-- Paling sering di-query
CREATE INDEX idx_price_ticker_date ON price_data(ticker, date DESC);
CREATE INDEX idx_broksum_ticker_date ON broker_summary(ticker, date DESC);
CREATE INDEX idx_signals_date ON signals(date DESC);
CREATE INDEX idx_signals_ticker ON signals(ticker, date DESC);
CREATE INDEX idx_foreign_ticker_date ON foreign_flow(ticker, date DESC);
```
