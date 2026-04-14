# PROMPT FASE 3 — News Sentiment + Streamlit Dashboard

> Gunakan SETELAH Fase 2 stabil dan broksum data sudah terkumpul > 1 bulan.

---

## PROMPT NEWS SENTIMENT

```
Tambahkan News Sentiment Engine ke WhaleDet IDX.

### Step 1: Database
Buat `scripts/migrations/003_news.sql`:
- Tabel `news_items` sesuai DATA_DICTIONARY.md

### Step 2: RSS Scraper
Buat `data/scrapers/news_rss.py`:

RSS feeds yang harus di-scrape:
```python
RSS_FEEDS = {
    "kontan": "https://www.kontan.co.id/rss/investasi",
    "bisnis": "https://market.bisnis.com/rss",  
    "cnbc_id": "https://www.cnbcindonesia.com/market/rss",
    "idx_announcement": "https://www.idx.co.id/umum/berita-dan-pengumuman/",
}
```

Fungsi:
- `fetch_all_rss() -> list[dict]` — ambil semua berita baru sejak kemarin
- `parse_rss_item(item: dict) -> dict` — extract headline, url, date, source
- Deduplicate berdasarkan URL

### Step 3: Sector Keyword Mapper
Buat `config/sector_keywords.py`:

```python
SECTOR_KEYWORDS = {
    r"(perkapalan|shipping|TMAS|WINS|BULL|MBSS)": 
        ["TMAS", "WINS", "BULL", "MBSS", "SHIP"],
    r"(sawit|CPO|B\d+|bioetanol|palm oil)": 
        ["SIMP", "AALI", "LSIP", "SSMS", "TAPG", "TBLA"],
    r"(batubara|coal|PTBA|ADRO)": 
        ["PTBA", "ADRO", "ITMG", "HRUM", "BYAN"],
    r"(nikel|nickel|EV|baterai|battery|INCO|VALE)": 
        ["INCO", "VALE", "NCKL", "ANTM"],
    r"(bank|perbankan|OJK|suku bunga|BI rate)": 
        ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS"],
    r"(properti|KPR|BSDE|SMRA)": 
        ["BSDE", "SMRA", "CTRA", "PWON", "LPKR"],
    r"(telekomunikasi|TLKM|XL|Indosat)": 
        ["TLKM", "EXCL", "ISAT", "MTEL"],
    r"(rokok|tembakau|HMSP|GGRM)":
        ["HMSP", "GGRM"],
    r"(IHSG|pasar saham|investor asing|foreign)":
        [],  # market-wide, tidak spesifik emiten
}

SOURCE_WEIGHTS = {
    "kontan.co.id": 0.85,
    "bisnis.com": 0.85, 
    "cnbcindonesia.com": 0.75,
    "detik.com": 0.50,
    "idx.co.id": 1.00,  # official, tertinggi
    "unknown": 0.30,
}
```

### Step 4: Sentiment Scorer
Buat `engine/news_sentiment.py`:

Gunakan rule-based (bukan ML) untuk fase ini — lebih predictable:

```python
POSITIVE_WORDS = {
    "high_confidence": ["disetujui", "implementasi", "ekspansi", "kontrak", 
                        "akuisisi", "dividen", "meningkat", "rekor"],
    "medium_confidence": ["positif", "naik", "tumbuh", "mendorong", "baik"]
}

NEGATIVE_WORDS = {
    "high_confidence": ["dilarang", "sanksi", "gagal", "kebangkrutan", 
                        "kerugian besar", "penundaan proyek"],
    "medium_confidence": ["turun", "merugi", "negatif", "masalah", "krisis"]
}
```

Fungsi:
- `analyze_sentiment(headline: str, source: str) -> dict`
  Returns: {score: float (-1 to 1), confidence: str, matched_words: list}

- `map_news_to_tickers(news_item: dict) -> list[str]`
  Returns: list ticker yang terdampak

- `compute_news_score(tickers_news: list[dict]) -> float`
  Aggregate sentiment untuk satu emiten (0-100)

### Step 5: Integration ke Main Pipeline
Update `main.py`:
- Scrape news setelah market close
- Map ke tickers
- Include news_score di composite scoring

Update bobot di scorer.py:
- volume: 25%, broker: 35%, foreign: 25%, news: 15%
```

---

## PROMPT STREAMLIT DASHBOARD

```
Buat Streamlit dashboard untuk WhaleDet IDX.

Buat `dashboard/app.py` dengan fitur berikut:

### Layout Utama
```
Sidebar:
- Date picker (default: hari ini)
- Filter sektor
- Filter tier (A/B/C)
- Filter score minimum (slider 0-100)
- Filter signal type (multiselect)

Main area:
- Tab 1: "Today's Signals" — tabel sinyal hari ini
- Tab 2: "Emiten Detail" — drill-down per emiten
- Tab 3: "Market Overview" — ringkasan market
- Tab 4: "News" — berita terbaru per sektor
```

### Tab 1: Today's Signals
- Tabel dengan kolom: Ticker, Score, Signal, Phase, Vol Z-Score, Streak, News
- Color coding: merah/kuning/hijau berdasarkan score
- Sortable dan filterable
- Klik ticker → redirect ke Tab 2

### Tab 2: Emiten Detail
- Input ticker selector
- Candlestick chart dengan volume (plotly)
- Tabel broksum 10 hari terakhir (warna merah/hijau untuk net)
- Foreign flow chart (line chart)
- News terkait emiten
- Signal history (skor 30 hari terakhir)

### Tab 3: Market Overview
- IHSG sparkline
- Top 5 sinyal hari ini
- Sektor heatmap (mana yang paling aktif)
- Volume market total vs rata-rata

### Tab 4: News
- News terbaru dikelompokkan per sektor
- Filter by sektor
- Sentiment indicator per berita

### Technical Requirements
- Data dari Supabase via supabase-py client
- Cache query dengan @st.cache_data(ttl=300)  # 5 menit cache
- Chart dengan plotly (bukan matplotlib)
- Mobile-friendly layout
- Dark theme
- Loading spinner saat fetch data

### Konfigurasi Deploy
Tambahkan `dashboard/requirements.txt` terpisah jika perlu library tambahan:
- streamlit>=1.30.0
- plotly>=5.18.0
- supabase>=2.0.0
- pandas>=2.0.0

Setelah selesai, tunjukkan cara deploy ke Streamlit Community Cloud.
```
