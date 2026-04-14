"""
backfill_ohlcv.py — Download OHLCV historis untuk backfill database.

Jalankan sekali saat setup awal. Setelah itu pipeline harian yang update.

Usage:
    python scripts/backfill_ohlcv.py --universe idx80 --years 1
    python scripts/backfill_ohlcv.py --universe idx300 --years 5
    python scripts/backfill_ohlcv.py --universe all --years 2 --dry-run
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from tqdm import tqdm

from config.settings import settings, configure_logging
from data.scrapers.ohlcv import fetch_ohlcv_batch
from output.db_writer import (
    load_emiten_universe,
    load_price_history_bulk,
    write_price_data,
)

logger = logging.getLogger(__name__)

# Rate limit ketat untuk backfill (lebih panjang dari daily run)
BACKFILL_DELAY_SEC = 1.0
BACKFILL_BATCH_SIZE = 30  # lebih kecil dari daily karena range panjang


def get_tickers_for_universe(universe_name: str) -> list[str]:
    """Ambil daftar ticker sesuai universe yang dipilih.

    Args:
        universe_name: "idx80", "idx300", atau "all"

    Returns:
        List ticker IDX
    """
    logger.info(f"Load universe '{universe_name}' dari Supabase...")

    if universe_name == "idx80":
        df = load_emiten_universe(filters={"is_idx80": True})
    elif universe_name == "idx300":
        df = load_emiten_universe(filters={"is_idx300": True})
    elif universe_name == "all":
        df = load_emiten_universe()
    else:
        logger.error(f"Universe tidak dikenal: {universe_name}")
        return []

    if df.empty:
        logger.error(
            "Tidak ada emiten di database. Jalankan scripts/seed_universe.py terlebih dahulu."
        )
        return []

    tickers = df["ticker"].tolist()
    logger.info(f"  {len(tickers)} ticker untuk universe '{universe_name}'")
    return tickers


def get_existing_ticker_dates(tickers: list[str], start: str, end: str) -> set[tuple[str, str]]:
    """Cek ticker-tanggal yang sudah ada di database untuk skip.

    Args:
        tickers: List ticker
        start: Tanggal mulai YYYY-MM-DD
        end: Tanggal akhir YYYY-MM-DD

    Returns:
        Set of (ticker, date_str) yang sudah ada.
    """
    if not settings.supabase_url:
        return set()

    try:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)

        existing: set[tuple[str, str]] = set()
        batch_size = 100

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            result = (
                client.table("price_data")
                .select("ticker, date")
                .in_("ticker", batch)
                .gte("date", start)
                .lte("date", end)
                .execute()
            )
            for row in result.data:
                existing.add((row["ticker"], row["date"]))

        logger.info(f"  {len(existing)} rows sudah ada di database (akan di-skip)")
        return existing

    except Exception as exc:
        logger.warning(f"Gagal cek data yang sudah ada: {exc}. Akan fetch semua.")
        return set()


def run_backfill(
    tickers: list[str],
    start: str,
    end: str,
    dry_run: bool = False,
) -> dict:
    """Jalankan backfill untuk list ticker dan range tanggal.

    Args:
        tickers: List ticker IDX
        start: Tanggal mulai YYYY-MM-DD
        end: Tanggal akhir YYYY-MM-DD
        dry_run: Jika True, tidak tulis ke database

    Returns:
        Dict ringkasan: {tickers_done, rows_written, errors}
    """
    summary = {"tickers_done": 0, "rows_written": 0, "errors": 0}

    # Proses per batch ticker untuk manajemen memori
    progress = tqdm(
        range(0, len(tickers), BACKFILL_BATCH_SIZE),
        desc="Backfill OHLCV",
        unit="batch",
    )

    for i in progress:
        batch_tickers = tickers[i : i + BACKFILL_BATCH_SIZE]
        progress.set_postfix({"ticker": batch_tickers[0], "batch": f"{i // BACKFILL_BATCH_SIZE + 1}"})

        try:
            df = fetch_ohlcv_batch(batch_tickers, start=start, end=end)

            if df.empty:
                logger.warning(f"Tidak ada data untuk batch {batch_tickers[:3]}...")
                summary["errors"] += 1
                continue

            rows_written = write_price_data(df, dry_run=dry_run)
            summary["tickers_done"] += len(batch_tickers)
            summary["rows_written"] += rows_written

            logger.debug(
                f"Batch {i // BACKFILL_BATCH_SIZE + 1}: "
                f"{len(batch_tickers)} ticker, {len(df)} rows fetched, {rows_written} rows written"
            )

        except Exception as exc:
            logger.error(f"Batch gagal ({batch_tickers[:3]}...): {exc}")
            summary["errors"] += 1

        # Rate limit ketat untuk backfill
        time.sleep(BACKFILL_DELAY_SEC)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill OHLCV historis ke Supabase")
    parser.add_argument(
        "--universe",
        choices=["idx80", "idx300", "all"],
        default="idx80",
        help="Universe emiten yang di-backfill (default: idx80)",
    )
    parser.add_argument(
        "--years",
        type=int,
        choices=range(1, 11),
        default=1,
        metavar="1-10",
        help="Jumlah tahun historis (default: 1)",
    )
    parser.add_argument(
        "--start",
        help="Tanggal mulai manual YYYY-MM-DD (override --years)",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="Tanggal akhir YYYY-MM-DD (default: hari ini)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Jangan tulis ke database")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    configure_logging(debug=args.debug)

    if not args.dry_run:
        try:
            settings.validate()
        except ValueError as exc:
            logger.error(f"Konfigurasi tidak valid: {exc}")
            sys.exit(1)

    # Tentukan range tanggal
    end_date = args.end
    if args.start:
        start_date = args.start
    else:
        start_dt = date.today() - timedelta(days=args.years * 365)
        start_date = start_dt.isoformat()

    logger.info(f"=== backfill_ohlcv.py ===")
    logger.info(f"Universe : {args.universe}")
    logger.info(f"Range    : {start_date} → {end_date}")
    logger.info(f"Dry run  : {args.dry_run}")

    # Ambil daftar ticker
    tickers = get_tickers_for_universe(args.universe)
    if not tickers:
        sys.exit(1)

    # Jalankan backfill
    logger.info(f"\nMemulai backfill untuk {len(tickers)} ticker...")
    summary = run_backfill(tickers, start=start_date, end=end_date, dry_run=args.dry_run)

    # Ringkasan
    print(f"\n{'='*50}")
    print(f"  Backfill Selesai")
    print(f"{'='*50}")
    print(f"  Ticker diproses : {summary['tickers_done']}")
    print(f"  Rows ditulis    : {summary['rows_written']}")
    print(f"  Errors          : {summary['errors']}")
    if args.dry_run:
        print(f"  [DRY RUN] Tidak ada yang ditulis ke database")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
