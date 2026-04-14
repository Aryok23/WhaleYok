"""
ohlcv.py — Fetcher OHLCV harian via yfinance.

Aturan:
- Ticker IDX di database: uppercase tanpa ".JK" (misal: BBCA)
- Ticker yfinance: tambahkan ".JK" (misal: BBCA.JK)
- Return empty DataFrame jika data tidak tersedia, JANGAN raise
- Rate limiting: batch max 50 ticker, jeda 1 detik antar batch
"""

import logging
import time
from datetime import datetime, date

import pandas as pd
import yfinance as yf

from config.settings import settings

logger = logging.getLogger(__name__)

# yfinance kadang return kolom dengan nama berbeda tergantung versi
_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}


def _to_yf_tickers(tickers: list[str]) -> list[str]:
    """Tambahkan suffix .JK ke list ticker IDX."""
    return [f"{t}.JK" for t in tickers]


def _strip_jk(ticker: str) -> str:
    """Hapus suffix .JK dari ticker yfinance."""
    return ticker.replace(".JK", "")


def _download_with_retry(
    yf_tickers: list[str],
    start: str,
    end: str,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Download dari yfinance dengan exponential backoff retry.

    Args:
        yf_tickers: List ticker dengan suffix .JK
        start: Tanggal mulai format YYYY-MM-DD
        end: Tanggal akhir format YYYY-MM-DD (exclusive)
        max_retries: Jumlah maksimal percobaan

    Returns:
        DataFrame mentah dari yfinance, atau DataFrame kosong jika gagal.
    """
    for attempt in range(1, max_retries + 1):
        try:
            raw = yf.download(
                tickers=yf_tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            return raw
        except Exception as exc:
            wait = 2 ** attempt
            if attempt < max_retries:
                logger.warning(
                    f"yfinance download attempt {attempt}/{max_retries} gagal: {exc}. "
                    f"Retry dalam {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(f"yfinance download gagal setelah {max_retries} percobaan: {exc}")
    return pd.DataFrame()


def _normalize_raw(raw: pd.DataFrame, yf_tickers: list[str]) -> pd.DataFrame:
    """Ubah output yfinance multi/single ticker ke format standar WhaleDet.

    Kolom output: date, ticker, open, high, low, close, volume
    """
    if raw.empty:
        return pd.DataFrame()

    records: list[dict] = []

    # yfinance multi-ticker: MultiIndex columns (metric, ticker)
    # yfinance single ticker: flat columns (Open, High, ...)
    is_multi = isinstance(raw.columns, pd.MultiIndex)

    for yf_t in yf_tickers:
        ticker = _strip_jk(yf_t)
        try:
            if is_multi:
                # Ambil subset kolom untuk ticker ini
                sub = raw.xs(yf_t, axis=1, level=1) if yf_t in raw.columns.get_level_values(1) else pd.DataFrame()
            else:
                sub = raw  # single ticker

            if sub.empty:
                logger.warning(f"Tidak ada data yfinance untuk {ticker}")
                continue

            # Rename kolom ke lowercase
            sub = sub.rename(columns=_COLUMN_MAP)
            sub = sub[["open", "high", "low", "close", "volume"]].copy()
            sub = sub.dropna(subset=["close"])
            sub.index = pd.to_datetime(sub.index).normalize()
            sub["ticker"] = ticker
            sub.index.name = "date"
            sub = sub.reset_index()
            sub["date"] = sub["date"].dt.date
            sub["volume"] = sub["volume"].fillna(0).astype("int64")
            records.append(sub)

        except Exception as exc:
            logger.warning(f"Gagal parse data untuk {ticker}: {exc}")
            continue

    if not records:
        return pd.DataFrame()

    result = pd.concat(records, ignore_index=True)
    # Reorder kolom
    cols = ["date", "ticker", "open", "high", "low", "close", "volume"]
    return result[[c for c in cols if c in result.columns]]


def fetch_ohlcv_daily(tickers: list[str], target_date: str) -> pd.DataFrame:
    """Fetch data OHLCV untuk satu tanggal spesifik.

    Catatan: yfinance interval harian tidak selalu tersedia untuk T+0 pada
    hari yang sama. Gunakan setelah jam 16.30 WIB.

    Args:
        tickers: List ticker IDX (uppercase, tanpa .JK)
        target_date: Tanggal format YYYY-MM-DD

    Returns:
        DataFrame kolom: date, ticker, open, high, low, close, volume
        Return DataFrame kosong jika tidak ada data.
    """
    if not tickers:
        logger.warning("fetch_ohlcv_daily dipanggil dengan list ticker kosong")
        return pd.DataFrame()

    # yfinance end date exclusive — ambil hari berikutnya
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Format tanggal tidak valid: {target_date}. Gunakan YYYY-MM-DD.")
        return pd.DataFrame()

    import calendar
    from datetime import timedelta
    end_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    all_frames: list[pd.DataFrame] = []
    yf_tickers = _to_yf_tickers(tickers)

    for i in range(0, len(yf_tickers), settings.batch_size_yfinance):
        batch = yf_tickers[i : i + settings.batch_size_yfinance]
        logger.info(
            f"Fetching OHLCV batch {i // settings.batch_size_yfinance + 1}: "
            f"{len(batch)} ticker untuk {target_date}"
        )
        raw = _download_with_retry(batch, start=target_date, end=end_date)
        frame = _normalize_raw(raw, batch)
        if not frame.empty:
            all_frames.append(frame)

        if i + settings.batch_size_yfinance < len(yf_tickers):
            time.sleep(settings.request_delay_sec)

    if not all_frames:
        logger.warning(f"Tidak ada data OHLCV untuk tanggal {target_date}")
        return pd.DataFrame()

    result = pd.concat(all_frames, ignore_index=True)
    # Filter hanya tanggal yang diminta (yfinance kadang return hari berbeda)
    result = result[result["date"] == datetime.strptime(target_date, "%Y-%m-%d").date()]
    logger.info(f"fetch_ohlcv_daily selesai: {len(result)} rows untuk {len(result['ticker'].unique())} ticker")
    return result


def fetch_ohlcv_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Fetch data OHLCV untuk range tanggal.

    Cocok untuk backfill historis.

    Args:
        tickers: List ticker IDX (uppercase, tanpa .JK)
        start: Tanggal mulai YYYY-MM-DD (inclusive)
        end: Tanggal akhir YYYY-MM-DD (inclusive)

    Returns:
        DataFrame kolom: date, ticker, open, high, low, close, volume
        Return DataFrame kosong jika tidak ada data.
    """
    if not tickers:
        logger.warning("fetch_ohlcv_batch dipanggil dengan list ticker kosong")
        return pd.DataFrame()

    # yfinance end exclusive
    from datetime import timedelta
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
        end_exclusive = end_dt.strftime("%Y-%m-%d")
    except ValueError:
        logger.error(f"Format tanggal tidak valid: start={start}, end={end}")
        return pd.DataFrame()

    all_frames: list[pd.DataFrame] = []
    yf_tickers = _to_yf_tickers(tickers)

    for i in range(0, len(yf_tickers), settings.batch_size_yfinance):
        batch = yf_tickers[i : i + settings.batch_size_yfinance]
        logger.info(
            f"Fetching OHLCV batch {i // settings.batch_size_yfinance + 1}/{(len(yf_tickers) - 1) // settings.batch_size_yfinance + 1}: "
            f"{len(batch)} ticker [{start} → {end}]"
        )
        raw = _download_with_retry(batch, start=start, end=end_exclusive)
        frame = _normalize_raw(raw, batch)
        if not frame.empty:
            all_frames.append(frame)

        if i + settings.batch_size_yfinance < len(yf_tickers):
            time.sleep(settings.request_delay_sec)

    if not all_frames:
        logger.warning(f"Tidak ada data OHLCV untuk range {start} → {end}")
        return pd.DataFrame()

    result = pd.concat(all_frames, ignore_index=True)
    logger.info(
        f"fetch_ohlcv_batch selesai: {len(result)} rows, "
        f"{len(result['ticker'].unique())} ticker, "
        f"{result['date'].min()} → {result['date'].max()}"
    )
    return result
