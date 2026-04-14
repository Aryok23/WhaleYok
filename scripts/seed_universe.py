"""
seed_universe.py — Populate tabel emiten_universe di Supabase.

Sumber data: file CSV di config/universe/ yang sudah diisi secara manual.
Script ini hanya UPSERT (tidak delete yang sudah ada).

Jalankan sekali saat setup awal atau saat update universe.

Usage:
    python scripts/seed_universe.py
    python scripts/seed_universe.py --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config.settings import settings, configure_logging
from output.db_writer import write_emiten_universe

logger = logging.getLogger(__name__)

# Path ke file universe
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_DIR = os.path.join(BASE_DIR, "config", "universe")

# Definisi file universe dan kolom yang relevan
UNIVERSE_FILES = {
    "idx80": os.path.join(UNIVERSE_DIR, "idx80.csv"),
    "idx300": os.path.join(UNIVERSE_DIR, "idx300.csv"),
    "gorengan": os.path.join(UNIVERSE_DIR, "gorengan_watchlist.csv"),
}


def load_universe_csv() -> pd.DataFrame:
    """Load dan merge semua universe CSV menjadi satu DataFrame.

    Returns:
        DataFrame dengan semua emiten dan flag is_lq45, is_idx80, is_idx300.
    """
    all_tickers: dict[str, dict] = {}

    # Load IDX300 dulu sebagai base
    idx300_path = UNIVERSE_FILES["idx300"]
    if os.path.exists(idx300_path):
        df300 = pd.read_csv(idx300_path)
        logger.info(f"  IDX300: {len(df300)} emiten dimuat dari {idx300_path}")
        for _, row in df300.iterrows():
            ticker = str(row["ticker"]).strip().upper()
            all_tickers[ticker] = {
                "ticker": ticker,
                "name": str(row.get("name", "")).strip(),
                "sector": str(row.get("sector", "")).strip(),
                "sub_sector": None,
                "papan": "Utama",
                "market_cap_tier": "mid",
                "is_lq45": False,
                "is_idx80": bool(row.get("is_idx80", False)),
                "is_idx300": True,
                "konglo_group": None,
                "listing_date": None,
                "is_ipo_new": False,
                "last_updated": date.today().isoformat(),
            }
    else:
        logger.warning(f"File IDX300 tidak ditemukan: {idx300_path}")

    # Load gorengan watchlist
    gorengan_path = UNIVERSE_FILES["gorengan"]
    if os.path.exists(gorengan_path):
        df_gorengan = pd.read_csv(gorengan_path)
        logger.info(f"  Gorengan: {len(df_gorengan)} emiten dimuat dari {gorengan_path}")
        for _, row in df_gorengan.iterrows():
            ticker = str(row["ticker"]).strip().upper()
            if ticker not in all_tickers:
                all_tickers[ticker] = {
                    "ticker": ticker,
                    "name": str(row.get("name", "")).strip(),
                    "sector": str(row.get("sector", "")).strip(),
                    "sub_sector": None,
                    "papan": "Pengembangan",
                    "market_cap_tier": "small",
                    "is_lq45": False,
                    "is_idx80": False,
                    "is_idx300": False,
                    "konglo_group": None,
                    "listing_date": None,
                    "is_ipo_new": False,
                    "last_updated": date.today().isoformat(),
                }
    else:
        logger.warning(f"File gorengan tidak ditemukan: {gorengan_path}")

    # Load IDX80, update flag
    idx80_path = UNIVERSE_FILES["idx80"]
    if os.path.exists(idx80_path):
        df80 = pd.read_csv(idx80_path)
        logger.info(f"  IDX80: {len(df80)} emiten dimuat dari {idx80_path}")
        for _, row in df80.iterrows():
            ticker = str(row["ticker"]).strip().upper()
            is_lq45 = bool(row.get("is_lq45", False))

            if ticker in all_tickers:
                # Update flags
                all_tickers[ticker]["is_idx80"] = True
                all_tickers[ticker]["is_idx300"] = True
                all_tickers[ticker]["is_lq45"] = is_lq45
                if is_lq45:
                    all_tickers[ticker]["market_cap_tier"] = "large"
            else:
                # Tambah emiten baru yang ada di IDX80 tapi mungkin belum di IDX300
                all_tickers[ticker] = {
                    "ticker": ticker,
                    "name": str(row.get("name", "")).strip(),
                    "sector": str(row.get("sector", "")).strip(),
                    "sub_sector": None,
                    "papan": "Utama",
                    "market_cap_tier": "large" if is_lq45 else "mid",
                    "is_lq45": is_lq45,
                    "is_idx80": True,
                    "is_idx300": True,
                    "konglo_group": None,
                    "listing_date": None,
                    "is_ipo_new": False,
                    "last_updated": date.today().isoformat(),
                }
    else:
        logger.warning(f"File IDX80 tidak ditemukan: {idx80_path}")

    if not all_tickers:
        logger.error("Tidak ada data universe yang bisa dimuat!")
        return pd.DataFrame()

    df = pd.DataFrame(list(all_tickers.values()))
    logger.info(f"  Total: {len(df)} emiten unik")
    return df


def enrich_with_yfinance(df: pd.DataFrame) -> pd.DataFrame:
    """Opsional: Enrichment metadata dari yfinance (nama, sektor, listing date).

    Hanya jalan kalau ada data kosong. Rate limit: 1 detik per ticker.

    Args:
        df: DataFrame emiten_universe

    Returns:
        DataFrame yang sudah di-enrich.
    """
    import time
    import yfinance as yf

    enriched = df.copy()
    need_enrich = enriched[enriched["name"].isna() | (enriched["name"] == "")].copy()

    if need_enrich.empty:
        logger.info("  Semua emiten sudah punya nama — skip yfinance enrichment")
        return enriched

    logger.info(f"  Enriching {len(need_enrich)} emiten via yfinance...")

    for idx, row in need_enrich.iterrows():
        ticker = row["ticker"]
        try:
            yf_ticker = yf.Ticker(f"{ticker}.JK")
            info = yf_ticker.info

            name = info.get("longName") or info.get("shortName") or ""
            sector = info.get("sector") or ""
            listing_date_ts = info.get("firstTradeDateEpochUtc")

            if name:
                enriched.at[idx, "name"] = name
            if sector:
                enriched.at[idx, "sector"] = sector
            if listing_date_ts:
                try:
                    from datetime import datetime
                    ld = datetime.fromtimestamp(listing_date_ts).date()
                    enriched.at[idx, "listing_date"] = ld.isoformat()
                    ipo_cutoff = date.today() - timedelta(days=90)
                    enriched.at[idx, "is_ipo_new"] = ld >= ipo_cutoff
                except Exception:
                    pass

            logger.debug(f"  {ticker}: enriched — {name or 'no name'}")
        except Exception as exc:
            logger.warning(f"  {ticker}: yfinance enrichment gagal: {exc}")

        time.sleep(1.0)  # rate limit

    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed universe emiten ke Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Jangan tulis ke database")
    parser.add_argument("--enrich", action="store_true", help="Enrich nama/sektor via yfinance")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    configure_logging(debug=args.debug)

    if not args.dry_run:
        try:
            settings.validate()
        except ValueError as exc:
            logger.error(f"Konfigurasi tidak valid: {exc}")
            sys.exit(1)

    logger.info("=== seed_universe.py ===")
    logger.info("Step 1: Load universe CSV...")
    df = load_universe_csv()

    if df.empty:
        logger.error("Gagal load universe. Periksa file CSV di config/universe/")
        sys.exit(1)

    if args.enrich:
        logger.info("Step 2: Enrich via yfinance...")
        df = enrich_with_yfinance(df)
    else:
        logger.info("Step 2: Skip enrichment (gunakan --enrich untuk aktifkan)")

    logger.info(f"Step 3: Upsert {len(df)} emiten ke Supabase...")
    written = write_emiten_universe(df, dry_run=args.dry_run)

    if args.dry_run:
        logger.info(f"[DRY RUN] Akan menulis {len(df)} emiten")
    else:
        logger.info(f"Selesai: {written} emiten ditulis ke Supabase")


if __name__ == "__main__":
    main()
