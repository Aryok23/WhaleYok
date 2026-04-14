"""
db_writer.py — Tulis data ke Supabase PostgreSQL.

Semua operasi adalah UPSERT (bukan insert) agar idempotent.
Bisa dijalankan ulang di hari yang sama tanpa duplikasi data.
"""

import json
import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
from supabase import create_client, Client

from config.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # rows per batch insert


def _get_client() -> Client:
    """Buat Supabase client dari settings."""
    return create_client(settings.supabase_url, settings.supabase_key)


def _serialize_value(v: Any) -> Any:
    """Konversi tipe Python ke tipe yang JSON-serializable untuk Supabase."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if pd.isna(v):
        return None
    if isinstance(v, float) and (v != v):  # NaN check
        return None
    return v


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Konversi DataFrame ke list dict yang siap di-upsert."""
    records = []
    for _, row in df.iterrows():
        record = {k: _serialize_value(v) for k, v in row.items()}
        records.append(record)
    return records


def write_price_data(df: pd.DataFrame, dry_run: bool = False) -> int:
    """Upsert data OHLCV harian ke tabel price_data.

    Args:
        df: DataFrame dengan kolom: date, ticker, open, high, low, close, volume
        dry_run: Jika True, tidak melakukan write ke database

    Returns:
        Jumlah rows yang berhasil ditulis (0 jika dry_run)
    """
    if df.empty:
        logger.warning("write_price_data: DataFrame kosong, tidak ada yang ditulis")
        return 0

    required_cols = {"date", "ticker", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        logger.error(f"write_price_data: kolom wajib tidak ada: {missing}")
        return 0

    # Tambahkan source jika belum ada
    df = df.copy()
    if "source" not in df.columns:
        df["source"] = "yfinance"

    if dry_run:
        logger.info(f"[DRY RUN] write_price_data: akan menulis {len(df)} rows")
        return 0

    client = _get_client()
    records = _df_to_records(df)
    total_written = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        try:
            client.table("price_data").upsert(batch, on_conflict="date,ticker").execute()
            total_written += len(batch)
            logger.debug(f"write_price_data: batch {i // BATCH_SIZE + 1} OK ({len(batch)} rows)")
        except Exception as exc:
            logger.error(f"write_price_data: gagal batch {i // BATCH_SIZE + 1}: {exc}")

    logger.info(f"write_price_data: {total_written}/{len(df)} rows ditulis")
    return total_written


def write_signals(signals: list[dict], dry_run: bool = False) -> int:
    """Upsert sinyal ke tabel signals.

    Upsert berdasarkan (date, ticker) — satu sinyal per emiten per hari.

    Args:
        signals: List dict dengan keys sesuai schema tabel signals.
                 evidence_json boleh berupa dict (akan di-serialize ke JSON).
        dry_run: Jika True, tidak melakukan write ke database

    Returns:
        Jumlah rows yang berhasil ditulis (0 jika dry_run)
    """
    if not signals:
        logger.warning("write_signals: list kosong, tidak ada yang ditulis")
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] write_signals: akan menulis {len(signals)} sinyal")
        for s in signals[:5]:  # log sample
            logger.info(f"  Sample: {s.get('ticker')} score={s.get('composite_score')}")
        return 0

    client = _get_client()

    # Serialize evidence_json ke string jika berupa dict
    prepared = []
    for sig in signals:
        s = dict(sig)
        if isinstance(s.get("evidence_json"), dict):
            s["evidence_json"] = json.dumps(s["evidence_json"])
        # Serialize date
        if isinstance(s.get("date"), (date, datetime)):
            s["date"] = s["date"].isoformat()
        prepared.append(s)

    total_written = 0
    for i in range(0, len(prepared), BATCH_SIZE):
        batch = prepared[i : i + BATCH_SIZE]
        try:
            client.table("signals").upsert(
                batch, on_conflict="date,ticker"
            ).execute()
            total_written += len(batch)
            logger.debug(f"write_signals: batch {i // BATCH_SIZE + 1} OK ({len(batch)} rows)")
        except Exception as exc:
            logger.error(f"write_signals: gagal batch {i // BATCH_SIZE + 1}: {exc}")

    logger.info(f"write_signals: {total_written}/{len(signals)} sinyal ditulis")
    return total_written


def write_emiten_universe(df: pd.DataFrame, dry_run: bool = False) -> int:
    """Upsert daftar emiten ke tabel emiten_universe.

    Args:
        df: DataFrame dengan kolom sesuai schema emiten_universe
        dry_run: Jika True, tidak melakukan write ke database

    Returns:
        Jumlah rows yang berhasil ditulis (0 jika dry_run)
    """
    if df.empty:
        logger.warning("write_emiten_universe: DataFrame kosong")
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] write_emiten_universe: akan menulis {len(df)} emiten")
        return 0

    client = _get_client()
    records = _df_to_records(df)
    total_written = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        try:
            client.table("emiten_universe").upsert(batch, on_conflict="ticker").execute()
            total_written += len(batch)
        except Exception as exc:
            logger.error(f"write_emiten_universe: gagal batch {i // BATCH_SIZE + 1}: {exc}")

    logger.info(f"write_emiten_universe: {total_written}/{len(df)} emiten ditulis")
    return total_written


def load_price_history(ticker: str, days: int = 30) -> pd.DataFrame:
    """Load historis price_data dari Supabase untuk satu ticker.

    Digunakan oleh engine/features.py untuk menghitung z-score.

    Args:
        ticker: Kode saham IDX (uppercase, tanpa .JK)
        days: Jumlah hari historis yang diambil

    Returns:
        DataFrame kolom: date, ticker, open, high, low, close, volume
        Return DataFrame kosong jika tidak ada data.
    """
    try:
        client = _get_client()
        response = (
            client.table("price_data")
            .select("date, ticker, open, high, low, close, volume")
            .eq("ticker", ticker)
            .order("date", desc=True)
            .limit(days)
            .execute()
        )
        if not response.data:
            return pd.DataFrame()

        df = pd.DataFrame(response.data)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        return df

    except Exception as exc:
        logger.error(f"load_price_history: gagal load {ticker}: {exc}")
        return pd.DataFrame()


def load_price_history_bulk(tickers: list[str], days: int = 30) -> pd.DataFrame:
    """Load historis price_data dari Supabase untuk banyak ticker sekaligus.

    Args:
        tickers: List kode saham IDX
        days: Jumlah hari historis yang diambil (per ticker)

    Returns:
        DataFrame kolom: date, ticker, open, high, low, close, volume
    """
    if not tickers:
        return pd.DataFrame()

    try:
        client = _get_client()
        # Ambil N hari terakhir untuk semua ticker yang diminta
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days + 10)).isoformat()  # +10 buffer weekend/holiday

        response = (
            client.table("price_data")
            .select("date, ticker, open, high, low, close, volume")
            .in_("ticker", tickers)
            .gte("date", cutoff)
            .order("date", desc=False)
            .execute()
        )
        if not response.data:
            return pd.DataFrame()

        df = pd.DataFrame(response.data)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    except Exception as exc:
        logger.error(f"load_price_history_bulk: gagal: {exc}")
        return pd.DataFrame()


def load_emiten_universe(filters: dict | None = None) -> pd.DataFrame:
    """Load daftar emiten dari Supabase.

    Args:
        filters: Dict optional, misal {"is_idx80": True}

    Returns:
        DataFrame dengan kolom emiten_universe.
    """
    try:
        client = _get_client()
        query = client.table("emiten_universe").select("*")

        if filters:
            for col, val in filters.items():
                query = query.eq(col, val)

        response = query.execute()
        if not response.data:
            return pd.DataFrame()

        df = pd.DataFrame(response.data)
        if "listing_date" in df.columns:
            df["listing_date"] = pd.to_datetime(df["listing_date"]).dt.date
        return df

    except Exception as exc:
        logger.error(f"load_emiten_universe: gagal: {exc}")
        return pd.DataFrame()


def mark_signals_sent(signal_ids: list[int], dry_run: bool = False) -> None:
    """Tandai sinyal sudah dikirim ke Telegram.

    Args:
        signal_ids: List ID dari tabel signals
        dry_run: Jika True, tidak melakukan update
    """
    if not signal_ids or dry_run:
        return

    try:
        client = _get_client()
        client.table("signals").update({"sent_to_telegram": True}).in_("id", signal_ids).execute()
        logger.debug(f"mark_signals_sent: {len(signal_ids)} sinyal ditandai sent")
    except Exception as exc:
        logger.error(f"mark_signals_sent: gagal: {exc}")
