"""
broksum.py — Scraper broker summary harian dari IDX.co.id.

Endpoint IDX:
  GET https://www.idx.co.id/primary/TradingSummary/GetBrokerSummary
  Params: code={ticker}, start=0, length=100, date={YYYY-MM-DD}

Rate limit: 1 detik antar request (wajib).
Retry: max 3x dengan exponential backoff.
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests

from config.broker_profiles import classify_broker

logger = logging.getLogger(__name__)

IDX_BROKSUM_URL = "https://www.idx.co.id/primary/TradingSummary/GetBrokerSummary"
IDX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-broker/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0   # detik, dikali 2 setiap retry
RATE_LIMIT_SEC = 1.5  # antar request


def _parse_broksum_response(data: list[dict], ticker: str, target_date: date) -> pd.DataFrame:
    """Parse respons JSON IDX menjadi DataFrame broker_summary.

    Args:
        data: List dict dari response["data"]
        ticker: Kode saham IDX
        target_date: Tanggal data

    Returns:
        DataFrame dengan kolom: date, ticker, broker_code, net_value, net_volume,
                                 buy_value, sell_value, freq_buy, freq_sell, category
    """
    if not data:
        return pd.DataFrame()

    records = []
    for row in data:
        broker_code = str(row.get("BrokerID", "")).strip().upper()
        if not broker_code:
            continue

        try:
            buy_value = float(row.get("BuyValue", 0) or 0)
            sell_value = float(row.get("SellValue", 0) or 0)
            buy_volume = float(row.get("BuyVolume", 0) or 0)
            sell_volume = float(row.get("SellVolume", 0) or 0)
            freq_buy = int(row.get("BuyFreq", 0) or 0)
            freq_sell = int(row.get("SellFreq", 0) or 0)
        except (ValueError, TypeError):
            continue

        net_value = buy_value - sell_value
        net_volume = buy_volume - sell_volume
        category = classify_broker(broker_code)

        records.append({
            "date": target_date.isoformat(),
            "ticker": ticker,
            "broker_code": broker_code,
            "buy_value": int(buy_value),
            "sell_value": int(sell_value),
            # net_value adalah GENERATED column — tidak perlu diinsert
            "buy_volume": int(buy_volume),
            "sell_volume": int(sell_volume),
            # net_volume adalah GENERATED column — tidak perlu diinsert
            "freq_buy": freq_buy,
            "freq_sell": freq_sell,
            "category": category,
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def scrape_broksum(
    ticker: str,
    target_date: Optional[date] = None,
    length: int = 100,
) -> pd.DataFrame:
    """Scrape broker summary untuk satu ticker satu hari dari IDX.

    Args:
        ticker: Kode saham IDX (uppercase, tanpa .JK)
        target_date: Tanggal data (default: hari ini)
        length: Jumlah broker yang diambil (default 100)

    Returns:
        DataFrame broker_summary. Kosong jika gagal atau tidak ada data.
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    params = {
        "code": ticker,
        "start": 0,
        "length": length,
        "date": date_str,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                IDX_BROKSUM_URL,
                params=params,
                headers=IDX_HEADERS,
                timeout=15,
            )

            if resp.status_code == 404:
                logger.warning(f"scrape_broksum: {ticker} {date_str} — 404, data tidak tersedia")
                return pd.DataFrame()

            resp.raise_for_status()
            payload = resp.json()

            data = payload.get("data", [])
            if not data:
                logger.warning(f"scrape_broksum: {ticker} {date_str} — respons kosong")
                return pd.DataFrame()

            df = _parse_broksum_response(data, ticker, target_date)
            if not df.empty:
                logger.debug(f"scrape_broksum: {ticker} {date_str} — {len(df)} broker")
            return df

        except requests.Timeout:
            logger.warning(f"scrape_broksum: timeout {ticker} attempt {attempt}/{MAX_RETRIES}")
        except requests.HTTPError as exc:
            logger.warning(f"scrape_broksum: HTTP error {ticker}: {exc} attempt {attempt}/{MAX_RETRIES}")
        except (ValueError, KeyError) as exc:
            logger.error(f"scrape_broksum: parse error {ticker}: {exc}")
            return pd.DataFrame()
        except requests.RequestException as exc:
            logger.warning(f"scrape_broksum: request error {ticker}: {exc} attempt {attempt}/{MAX_RETRIES}")

        if attempt < MAX_RETRIES:
            sleep_time = RETRY_BACKOFF ** attempt
            logger.debug(f"scrape_broksum: retry {attempt} in {sleep_time:.1f}s")
            time.sleep(sleep_time)

    logger.error(f"scrape_broksum: {ticker} {date_str} gagal setelah {MAX_RETRIES} retry")
    return pd.DataFrame()


def scrape_broksum_bulk(
    tickers: list[str],
    target_date: Optional[date] = None,
) -> pd.DataFrame:
    """Scrape broker summary untuk banyak ticker sekaligus.

    Args:
        tickers: List kode saham IDX
        target_date: Tanggal data (default: hari ini)

    Returns:
        DataFrame gabungan semua ticker. Kosong jika semua gagal.
    """
    if target_date is None:
        target_date = date.today()

    all_dfs = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.debug(f"scrape_broksum_bulk: [{i}/{total}] {ticker}")
        df = scrape_broksum(ticker, target_date)
        if not df.empty:
            all_dfs.append(df)
        time.sleep(RATE_LIMIT_SEC)

    if not all_dfs:
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        f"scrape_broksum_bulk: selesai {len(all_dfs)}/{total} ticker, "
        f"{len(result)} rows total"
    )
    return result


def compute_broker_net_by_category(broksum_df: pd.DataFrame) -> dict:
    """Hitung total net value per kategori broker untuk satu ticker.

    Args:
        broksum_df: Output dari scrape_broksum() untuk satu ticker.

    Returns:
        Dict: {
            "asing_net": float,       # net value broker asing (Rupiah)
            "institusi_net": float,   # net value broker institusi
            "retail_net": float,      # net value broker retail
            "asing_dominan": bool,    # True jika asing adalah net buyer terbesar
            "smart_money_net": float, # asing + institusi
        }
    """
    if broksum_df.empty:
        return {
            "asing_net": 0.0,
            "institusi_net": 0.0,
            "retail_net": 0.0,
            "asing_dominan": False,
            "smart_money_net": 0.0,
        }

    asing_net = float(
        broksum_df[broksum_df["category"] == "ASING"]["net_value"].sum()
    )
    institusi_net = float(
        broksum_df[broksum_df["category"] == "INSTITUSI"]["net_value"].sum()
    )
    retail_net = float(
        broksum_df[broksum_df["category"] == "RETAIL"]["net_value"].sum()
    )
    smart_money_net = asing_net + institusi_net

    return {
        "asing_net": asing_net,
        "institusi_net": institusi_net,
        "retail_net": retail_net,
        "asing_dominan": asing_net > 0 and asing_net >= institusi_net,
        "smart_money_net": smart_money_net,
    }
