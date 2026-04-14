"""
backfill_broksum.py — Backfill broker summary historis ke Supabase via Stockbit.

Stockbit (exodus.stockbit.com) menyimpan data broksum buy/sell per broker per hari.
  Endpoint: GET /order-trade/broker/distribution
  Auth: Bearer token dari STOCKBIT_TOKEN di .env (valid ~24 jam)
  Data: top 12 buyer + top 12 seller per hari per saham

Script ini iterasi per-tanggal, per-ticker — karena endpoint hanya menerima
satu tanggal sekaligus.

Usage:
    # Backfill 5 hari terakhir (default), universe idx80
    python scripts/backfill_broksum.py

    # Backfill tanggal spesifik, universe idx80
    python scripts/backfill_broksum.py --start 2026-04-07 --end 2026-04-13 --universe idx80

    # Universe gorengan
    python scripts/backfill_broksum.py --start 2026-04-07 --end 2026-04-13 --universe gorengan

    # Dry run — tidak tulis ke database
    python scripts/backfill_broksum.py --dry-run --debug
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config.settings import settings, configure_logging
from data.scrapers.broksum import scrape_broksum_stockbit
from output.db_writer import write_broker_summary

logger = logging.getLogger(__name__)

# Direktori universe CSV
UNIVERSE_DIR = Path(__file__).parent.parent / "config" / "universe"

# Delay antar request (lebih konservatif untuk backfill)
BACKFILL_RATE_LIMIT_SEC = 1.0


def _get_trading_days(start: date, end: date) -> list[date]:
    """Hasilkan list hari bursa (Senin–Jumat) antara start dan end (inklusif).

    Tidak memperhitungkan libur nasional Indonesia — hari libur akan menghasilkan
    response kosong dari IDX dan di-skip secara otomatis.

    Args:
        start: Tanggal mulai
        end: Tanggal akhir (inklusif)

    Returns:
        List tanggal hari kerja (weekday), dari start ke end.
    """
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Senin, 4=Jumat
            days.append(current)
        current += timedelta(days=1)
    return days


def _load_tickers_from_csv(csv_filename: str) -> list[str]:
    """Load daftar ticker dari file CSV di config/universe/.

    Args:
        csv_filename: Nama file CSV (misal "idx80.csv")

    Returns:
        List ticker IDX uppercase.
    """
    csv_path = UNIVERSE_DIR / csv_filename
    if not csv_path.exists():
        logger.error(f"File universe tidak ditemukan: {csv_path}")
        return []

    try:
        df = pd.read_csv(csv_path)
        if "ticker" not in df.columns:
            logger.error(f"{csv_filename}: kolom 'ticker' tidak ditemukan")
            return []
        tickers = df["ticker"].dropna().str.strip().str.upper().tolist()
        logger.info(f"  {len(tickers)} ticker dari {csv_filename}")
        return tickers
    except Exception as exc:
        logger.error(f"Gagal baca {csv_filename}: {exc}")
        return []


def get_tickers_for_universe(universe_name: str) -> list[str]:
    """Ambil daftar ticker sesuai universe yang dipilih.

    Baca langsung dari CSV (tidak perlu Supabase) agar bisa dijalankan
    bahkan sebelum seed_universe.py.

    Args:
        universe_name: "idx80", "idx300", "gorengan", atau "all"

    Returns:
        List ticker IDX unik, deduplikasi.
    """
    logger.info(f"Load universe '{universe_name}' dari CSV...")

    mapping = {
        "idx80": ["idx80.csv"],
        "idx300": ["idx300.csv"],
        "gorengan": ["gorengan_watchlist.csv"],
        "all": ["idx80.csv", "idx300.csv", "gorengan_watchlist.csv"],
    }

    if universe_name not in mapping:
        logger.error(f"Universe tidak dikenal: {universe_name}. Pilihan: {list(mapping.keys())}")
        return []

    all_tickers: list[str] = []
    for csv_file in mapping[universe_name]:
        all_tickers.extend(_load_tickers_from_csv(csv_file))

    # Deduplikasi, pertahankan urutan
    seen: set[str] = set()
    unique_tickers: list[str] = []
    for t in all_tickers:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    logger.info(f"  Total: {len(unique_tickers)} ticker unik")
    return unique_tickers


def run_backfill(
    tickers: list[str],
    trading_days: list[date],
    token: str,
    dry_run: bool = False,
) -> dict:
    """Jalankan backfill broksum untuk kombinasi ticker × tanggal via Stockbit.

    Iterasi per-tanggal (outer loop) lalu per-ticker (inner loop).
    Setiap tanggal diproses tuntas sebelum lanjut ke tanggal berikutnya,
    sehingga jika script diinterupsi, tanggal yang sudah selesai sudah tersimpan.

    Args:
        tickers: List ticker IDX
        trading_days: List tanggal hari bursa
        token: Bearer token Stockbit
        dry_run: Jika True, tidak tulis ke database

    Returns:
        Dict ringkasan hasil backfill.
    """
    summary = {
        "dates_processed": 0,
        "tickers_ok": 0,
        "tickers_empty": 0,
        "rows_written": 0,
        "errors": 0,
    }

    total_dates = len(trading_days)
    total_tickers = len(tickers)

    logger.info(
        f"Mulai backfill: {total_dates} tanggal × {total_tickers} ticker "
        f"= {total_dates * total_tickers} requests (estimasi)"
    )

    for day_idx, target_date in enumerate(trading_days, 1):
        date_str = target_date.isoformat()
        logger.info(
            f"\n[{day_idx}/{total_dates}] Scraping broksum tanggal {date_str}..."
        )

        day_dfs: list[pd.DataFrame] = []
        day_ok = 0
        day_empty = 0

        for t_idx, ticker in enumerate(tickers, 1):
            df = scrape_broksum_stockbit(ticker, target_date=target_date, token=token)

            if not df.empty:
                day_dfs.append(df)
                day_ok += 1
                logger.debug(
                    f"  [{t_idx}/{total_tickers}] {ticker}: {len(df)} broker rows"
                )
            else:
                day_empty += 1
                logger.debug(
                    f"  [{t_idx}/{total_tickers}] {ticker}: kosong (hari libur/data tidak tersedia)"
                )

            # Rate limit wajib
            time.sleep(BACKFILL_RATE_LIMIT_SEC)

        # Simpan semua data hari ini sekaligus (satu batch per tanggal)
        rows_written_today = 0
        if day_dfs:
            combined = pd.concat(day_dfs, ignore_index=True)
            rows_written_today = write_broker_summary(combined, dry_run=dry_run)
            logger.info(
                f"  {date_str}: {day_ok} ticker OK, {day_empty} kosong — "
                f"{rows_written_today} rows {'[DRY RUN]' if dry_run else 'ditulis ke DB'}"
            )
        else:
            logger.warning(
                f"  {date_str}: semua ticker kosong — kemungkinan hari libur, skip"
            )

        summary["dates_processed"] += 1
        summary["tickers_ok"] += day_ok
        summary["tickers_empty"] += day_empty
        summary["rows_written"] += rows_written_today

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill broker summary historis ke Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--universe",
        choices=["idx80", "idx300", "gorengan", "all"],
        default="idx80",
        help="Universe emiten (default: idx80). 'all' = idx80 + idx300 + gorengan",
    )
    parser.add_argument(
        "--start",
        default=None,
        help=(
            "Tanggal mulai YYYY-MM-DD. "
            "Default: 5 hari bursa ke belakang dari --end."
        ),
    )
    parser.add_argument(
        "--end",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="Tanggal akhir YYYY-MM-DD (default: kemarin)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Jangan tulis ke database — hanya tampilkan apa yang akan dilakukan",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    configure_logging(debug=args.debug)

    # Validasi token Stockbit
    token = settings.stockbit_token
    if not token:
        logger.error(
            "STOCKBIT_TOKEN tidak ditemukan di .env. "
            "Isi dengan Bearer token dari exodus.stockbit.com."
        )
        sys.exit(1)

    # Validasi Supabase connection (kecuali dry-run)
    if not args.dry_run:
        try:
            settings.validate()
        except ValueError as exc:
            logger.error(f"Konfigurasi tidak valid: {exc}")
            sys.exit(1)

    # Parse end date
    try:
        end_date = date.fromisoformat(args.end)
    except ValueError:
        logger.error(f"Format --end tidak valid: {args.end}. Gunakan YYYY-MM-DD.")
        sys.exit(1)

    # Parse start date (atau hitung otomatis 5 hari bursa ke belakang)
    if args.start:
        try:
            start_date = date.fromisoformat(args.start)
        except ValueError:
            logger.error(f"Format --start tidak valid: {args.start}. Gunakan YYYY-MM-DD.")
            sys.exit(1)
    else:
        # Hitung 5 hari bursa ke belakang dari end_date
        counting = end_date
        bursa_days_found = 0
        while bursa_days_found < 5:
            if counting.weekday() < 5:
                bursa_days_found += 1
                if bursa_days_found < 5:
                    counting -= timedelta(days=1)
            else:
                counting -= timedelta(days=1)
        start_date = counting

    if start_date > end_date:
        logger.error(f"--start ({start_date}) harus lebih awal dari --end ({end_date})")
        sys.exit(1)

    # Hitung hari bursa dalam range
    trading_days = _get_trading_days(start_date, end_date)
    if not trading_days:
        logger.error(f"Tidak ada hari bursa antara {start_date} dan {end_date}")
        sys.exit(1)

    # Load ticker
    tickers = get_tickers_for_universe(args.universe)
    if not tickers:
        sys.exit(1)

    # Estimasi waktu
    total_requests = len(trading_days) * len(tickers)
    est_minutes = (total_requests * BACKFILL_RATE_LIMIT_SEC) / 60

    logger.info(f"\n{'='*60}")
    logger.info(f"  Backfill Broksum")
    logger.info(f"{'='*60}")
    logger.info(f"  Universe  : {args.universe} ({len(tickers)} ticker)")
    logger.info(f"  Range     : {start_date} → {end_date}")
    logger.info(f"  Hari bursa: {len(trading_days)} hari — {[d.isoformat() for d in trading_days]}")
    logger.info(f"  Total req : ~{total_requests} requests")
    logger.info(f"  Est. waktu: ~{est_minutes:.1f} menit")
    logger.info(f"  Token     : {token[:20]}...")
    logger.info(f"  Dry run   : {args.dry_run}")
    logger.info(f"{'='*60}\n")

    # Jalankan backfill
    summary = run_backfill(tickers, trading_days, token=token, dry_run=args.dry_run)

    # Ringkasan akhir
    print(f"\n{'='*60}")
    print(f"  Backfill Broksum Selesai")
    print(f"{'='*60}")
    print(f"  Tanggal diproses : {summary['dates_processed']}")
    print(f"  Ticker berhasil  : {summary['tickers_ok']}")
    print(f"  Ticker kosong    : {summary['tickers_empty']} (libur/tidak ada data)")
    print(f"  Rows ditulis     : {summary['rows_written']}")
    if args.dry_run:
        print(f"  [DRY RUN] Tidak ada yang ditulis ke database")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
