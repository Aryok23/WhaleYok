"""
main.py — Entry point pipeline WhaleDet IDX.

Alur EOD:
  1. Load config (validasi env vars)
  2. Load universe emiten dari Supabase
  3. Fetch OHLCV hari ini untuk semua emiten
  4. Load OHLCV historis dari Supabase (untuk z-score rolling window)
  5. Compute features per emiten
  6. Score semua emiten
  7. Filter: ambil yang score > 50
  8. Sort by score descending
  9. Kirim top 10 ke Telegram
 10. Simpan semua signals ke Supabase
 11. Log ringkasan

Usage:
    python main.py --mode eod
    python main.py --mode eod --date 2026-04-11
    python main.py --mode eod --dry-run --debug
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from config.settings import settings, configure_logging
from data.scrapers.ohlcv import fetch_ohlcv_daily
from data.scrapers.broksum import scrape_broksum_bulk, compute_broker_net_by_category
from data.scrapers.foreign_flow import scrape_foreign_flow_bulk, compute_foreign_trend
from engine.features import compute_features_for_ticker
from engine.scorer import score_all_emiten
from output.db_writer import (
    load_emiten_universe,
    load_price_history_bulk,
    load_foreign_flow_history,
    write_price_data,
    write_broker_summary,
    write_foreign_flow,
    write_signals,
    mark_signals_sent,
)
from output.telegram_bot import send_eod_alert

logger = logging.getLogger(__name__)

# Jumlah hari historis yang diload untuk z-score
HISTORY_DAYS_FOR_ZSCORE = 40  # ambil 40 hari, pakai 20 untuk window


def parse_args() -> argparse.Namespace:
    """Parse argumen CLI."""
    parser = argparse.ArgumentParser(
        description="WhaleDet IDX — Pipeline deteksi aktivitas institusional"
    )
    parser.add_argument(
        "--mode",
        choices=["eod"],
        default="eod",
        help="Mode pipeline (default: eod)",
    )
    parser.add_argument(
        "--date",
        default="today",
        help="Tanggal scan format YYYY-MM-DD atau 'today' (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Jalankan pipeline tanpa menulis ke DB atau kirim Telegram",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Verbose logging (level DEBUG)",
    )
    return parser.parse_args()


def resolve_date(date_arg: str) -> date:
    """Resolve argumen tanggal ke objek date.

    Args:
        date_arg: "today" atau format YYYY-MM-DD

    Returns:
        date object
    """
    if date_arg == "today":
        return date.today()
    try:
        return datetime.strptime(date_arg, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Format tanggal tidak valid: {date_arg}. Gunakan YYYY-MM-DD.")
        sys.exit(1)


def run_eod_pipeline(target_date: date, dry_run: bool = False) -> dict:
    """Jalankan pipeline EOD untuk satu tanggal.

    Args:
        target_date: Tanggal scan
        dry_run: Jika True, tidak tulis ke DB dan tidak kirim Telegram

    Returns:
        Dict ringkasan hasil pipeline:
        {
            "date": str,
            "emiten_scanned": int,
            "signals_generated": int,
            "signals_alerted": int,
            "errors": int,
        }
    """
    date_str = target_date.isoformat()
    summary = {
        "date": date_str,
        "emiten_scanned": 0,
        "signals_generated": 0,
        "signals_alerted": 0,
        "errors": 0,
    }

    logger.info(f"=== WhaleDet EOD Pipeline: {date_str} {'[DRY RUN]' if dry_run else ''} ===")

    # ── Step 1: Load universe emiten ──────────────────────────────────────────
    logger.info("Step 1: Load universe emiten dari Supabase...")
    universe_df = load_emiten_universe()

    if universe_df.empty:
        logger.error(
            "Universe emiten kosong! Jalankan scripts/seed_universe.py terlebih dahulu."
        )
        summary["errors"] += 1
        return summary

    tickers = universe_df["ticker"].tolist()
    logger.info(f"  {len(tickers)} emiten dimuat dari universe")

    # ── Step 2: Fetch OHLCV hari ini ──────────────────────────────────────────
    logger.info(f"Step 2: Fetch OHLCV hari ini ({date_str}) via yfinance...")
    today_df = fetch_ohlcv_daily(tickers, date_str)

    if today_df.empty:
        logger.warning(
            f"Tidak ada data OHLCV untuk {date_str}. "
            f"Kemungkinan hari libur atau pasar belum tutup."
        )
        # Bukan error fatal — mungkin weekend/holiday
        summary["errors"] += 1
        return summary

    logger.info(f"  {len(today_df)} rows OHLCV diterima untuk {len(today_df['ticker'].unique())} ticker")

    # ── Step 3: Simpan OHLCV hari ini ke Supabase ─────────────────────────────
    logger.info("Step 3: Simpan OHLCV ke Supabase...")
    rows_written = write_price_data(today_df, dry_run=dry_run)
    logger.info(f"  {rows_written} rows ditulis (dry_run={dry_run})")

    # ── Step 4: Load historis untuk z-score ───────────────────────────────────
    logger.info(f"Step 4: Load {HISTORY_DAYS_FOR_ZSCORE} hari historis dari Supabase...")
    tickers_today = today_df["ticker"].unique().tolist()
    history_df = load_price_history_bulk(tickers_today, days=HISTORY_DAYS_FOR_ZSCORE)

    if history_df.empty:
        logger.warning(
            "Tidak ada data historis di Supabase. "
            "Z-score tidak bisa dihitung. Jalankan scripts/backfill_ohlcv.py."
        )
        # Tetap lanjutkan — akan ada banyak NaN tapi tidak crash
    else:
        logger.info(f"  {len(history_df)} rows historis dimuat")

    # ── Step 5: Scrape broker summary ─────────────────────────────────────────
    logger.info("Step 5: Scrape broker summary dari IDX...")
    broksum_df = scrape_broksum_bulk(tickers_today, target_date)
    broker_rows_written = write_broker_summary(broksum_df, dry_run=dry_run)
    logger.info(f"  {len(broksum_df)} broker rows diterima, {broker_rows_written} ditulis")

    # Build broker_map: {ticker: broker_category_summary}
    broker_map: dict[str, dict] = {}
    if not broksum_df.empty:
        for ticker in tickers_today:
            ticker_brok = broksum_df[broksum_df["ticker"] == ticker]
            if not ticker_brok.empty:
                broker_map[ticker] = compute_broker_net_by_category(ticker_brok)

    # ── Step 6: Scrape foreign flow ────────────────────────────────────────────
    logger.info("Step 6: Scrape foreign flow dari IDX...")
    foreign_df = scrape_foreign_flow_bulk(tickers_today, target_date)
    foreign_rows_written = write_foreign_flow(foreign_df, dry_run=dry_run)
    logger.info(f"  {len(foreign_df)} foreign rows diterima, {foreign_rows_written} ditulis")

    # Build foreign_map: {ticker: foreign_trend_data}
    foreign_map: dict[str, dict] = {}
    if not foreign_df.empty:
        for _, row in foreign_df.iterrows():
            ticker = row["ticker"]
            ff_hist = load_foreign_flow_history(ticker, days=20)
            trend_data = compute_foreign_trend(ticker, ff_hist)
            # _foreign_net = net hari ini (tidak tersimpan di DB, hanya untuk scoring)
            trend_data["foreign_net"] = row.get("_foreign_net", 0.0)
            foreign_map[ticker] = trend_data

    # ── Step 7: Compute features per emiten ───────────────────────────────────
    logger.info("Step 7: Compute features per emiten...")
    features_list: list[dict] = []
    errors_features = 0

    import pandas as pd

    for ticker in tickers_today:
        try:
            ticker_hist = history_df[history_df["ticker"] == ticker].copy() if not history_df.empty else pd.DataFrame()
            ticker_today = today_df[today_df["ticker"] == ticker].copy()

            if not ticker_hist.empty:
                combined = pd.concat([ticker_hist, ticker_today], ignore_index=True)
                combined = combined.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            else:
                combined = ticker_today.sort_values("date").reset_index(drop=True)

            if combined.empty:
                continue

            features = compute_features_for_ticker(combined, window=settings.volume_zscore_window)
            if features is not None:
                features_list.append(features)

        except Exception as exc:
            logger.warning(f"  Gagal compute features untuk {ticker}: {exc}")
            errors_features += 1

    summary["emiten_scanned"] = len(features_list)
    summary["errors"] += errors_features
    logger.info(f"  {len(features_list)} emiten berhasil dikomputasi features-nya")

    if errors_features > 0:
        logger.warning(f"  {errors_features} emiten gagal")

    # ── Step 8: Score semua emiten ────────────────────────────────────────────
    logger.info("Step 8: Score semua emiten...")
    # Fase 2 jika ada data broker atau foreign, fallback ke fase 1
    fase = 2 if (broker_map or foreign_map) else 1
    all_signals = score_all_emiten(
        features_list,
        broker_map=broker_map if broker_map else None,
        foreign_map=foreign_map if foreign_map else None,
        fase=fase,
    )
    logger.info(f"  {len(all_signals)} sinyal dihasilkan (fase {fase})")

    # ── Step 9: Filter sinyal signifikan ──────────────────────────────────────
    logger.info(f"Step 9: Filter sinyal dengan score >= {settings.min_score_for_alert}...")
    alert_signals = [s for s in all_signals if s["composite_score"] >= settings.min_score_for_alert]
    logger.info(f"  {len(alert_signals)} sinyal memenuhi threshold")

    summary["signals_generated"] = len(all_signals)

    # ── Step 10: Kirim top N ke Telegram ──────────────────────────────────────
    top_signals = alert_signals[: settings.top_n_signals]
    summary["signals_alerted"] = len(top_signals)

    logger.info(f"Step 10: Kirim {len(top_signals)} top sinyal ke Telegram...")
    telegram_ok = send_eod_alert(
        signals=top_signals,
        target_date=target_date,
        total_scanned=len(features_list),
        dry_run=dry_run,
    )
    if not telegram_ok:
        logger.warning("Satu atau lebih pesan Telegram gagal dikirim")

    # ── Step 11: Simpan semua signals ke Supabase ─────────────────────────────
    logger.info("Step 11: Simpan signals ke Supabase...")
    # Untuk setiap sinyal, tambahkan tier dari universe
    ticker_to_tier = {}
    if not universe_df.empty:
        for _, row in universe_df.iterrows():
            t = row["ticker"]
            if row.get("is_idx80"):
                ticker_to_tier[t] = "A"
            elif row.get("is_idx300"):
                ticker_to_tier[t] = "B"
            else:
                ticker_to_tier[t] = "C"

    signals_to_write = []
    for sig in all_signals:
        sig_copy = dict(sig)
        sig_copy["tier"] = ticker_to_tier.get(sig["ticker"], "C")
        sig_copy["sent_to_telegram"] = sig["ticker"] in {s["ticker"] for s in top_signals}
        signals_to_write.append(sig_copy)

    signals_written = write_signals(signals_to_write, dry_run=dry_run)
    logger.info(f"  {signals_written} sinyal ditulis ke Supabase")

    # ── Step 12: Ringkasan ────────────────────────────────────────────────────
    logger.info("=== PIPELINE SELESAI ===")
    logger.info(f"  Tanggal       : {date_str}")
    logger.info(f"  Emiten scan   : {summary['emiten_scanned']}")
    logger.info(f"  Total sinyal  : {summary['signals_generated']}")
    logger.info(f"  Alert dikirim : {summary['signals_alerted']}")
    logger.info(f"  Errors        : {summary['errors']}")
    if dry_run:
        logger.info("  [DRY RUN] Tidak ada data yang ditulis ke DB atau Telegram")

    return summary


def main() -> None:
    """Entry point utama."""
    args = parse_args()

    configure_logging(debug=args.debug)
    settings.debug = args.debug
    settings.dry_run = args.dry_run

    # Validasi config
    try:
        if not args.dry_run:
            settings.validate()
        else:
            # Dry run: hanya warn kalau env vars kosong, jangan exit
            missing = settings.validate_partial(
                "SUPABASE_URL", "SUPABASE_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
            )
            if missing:
                logger.warning(f"[DRY RUN] Env vars tidak dikonfigurasi: {missing}")
    except ValueError as exc:
        logger.error(f"Konfigurasi tidak valid: {exc}")
        sys.exit(1)

    target_date = resolve_date(args.date)

    if args.mode == "eod":
        summary = run_eod_pipeline(target_date, dry_run=args.dry_run)
        if summary["errors"] > 0 and summary["emiten_scanned"] == 0:
            sys.exit(1)
    else:
        logger.error(f"Mode tidak dikenal: {args.mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
