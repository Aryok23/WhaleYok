"""
foreign_flow.py — Scraper foreign net buy/sell harian dari IDX.co.id.

Endpoint IDX:
  GET https://www.idx.co.id/primary/TradingSummary/GetForeignSummary
  Params: code={ticker}, start=0, length=10, date={YYYY-MM-DD}

Rate limit: 1 detik antar request (wajib).
Retry: max 3x dengan exponential backoff.
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

IDX_FOREIGN_URL = "https://www.idx.co.id/primary/TradingSummary/GetForeignSummary"
IDX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-asing/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
RATE_LIMIT_SEC = 1.5


def scrape_foreign_flow(
    ticker: str,
    target_date: Optional[date] = None,
) -> Optional[dict]:
    """Scrape foreign net buy/sell untuk satu ticker satu hari dari IDX.

    Args:
        ticker: Kode saham IDX (uppercase, tanpa .JK)
        target_date: Tanggal data (default: hari ini)

    Returns:
        Dict berisi data foreign flow, atau None jika gagal.
        Keys: ticker, date, foreign_buy, foreign_sell, foreign_net,
              foreign_buy_volume, foreign_sell_volume, foreign_net_volume
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    params = {
        "code": ticker,
        "start": 0,
        "length": 10,
        "date": date_str,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                IDX_FOREIGN_URL,
                params=params,
                headers=IDX_HEADERS,
                timeout=15,
            )

            if resp.status_code == 404:
                logger.warning(f"scrape_foreign_flow: {ticker} {date_str} — 404")
                return None

            resp.raise_for_status()
            payload = resp.json()

            data = payload.get("data", [])
            if not data:
                logger.warning(f"scrape_foreign_flow: {ticker} {date_str} — respons kosong")
                return None

            row = data[0]
            try:
                foreign_buy = float(row.get("ForeignBuy", 0) or 0)
                foreign_sell = float(row.get("ForeignSell", 0) or 0)
                foreign_buy_vol = float(row.get("ForeignBuyVolume", 0) or 0)
                foreign_sell_vol = float(row.get("ForeignSellVolume", 0) or 0)
            except (ValueError, TypeError) as exc:
                logger.error(f"scrape_foreign_flow: parse error {ticker}: {exc}")
                return None

            result = {
                "ticker": ticker,
                "date": target_date.isoformat(),
                "foreign_buy": int(foreign_buy),
                "foreign_sell": int(foreign_sell),
                # foreign_net adalah GENERATED column — tidak perlu diinsert
                "foreign_buy_volume": int(foreign_buy_vol),
                "foreign_sell_volume": int(foreign_sell_vol),
                # foreign_net_volume adalah GENERATED column — tidak perlu diinsert
                # simpan net di key terpisah untuk kebutuhan scoring (tidak ditulis ke DB)
                "_foreign_net": foreign_buy - foreign_sell,
            }
            logger.debug(
                f"scrape_foreign_flow: {ticker} {date_str} "
                f"net={result['_foreign_net']:+.0f}"
            )
            return result

        except requests.Timeout:
            logger.warning(f"scrape_foreign_flow: timeout {ticker} attempt {attempt}/{MAX_RETRIES}")
        except requests.HTTPError as exc:
            logger.warning(f"scrape_foreign_flow: HTTP error {ticker}: {exc}")
        except requests.RequestException as exc:
            logger.warning(f"scrape_foreign_flow: request error {ticker}: {exc}")

        if attempt < MAX_RETRIES:
            sleep_time = RETRY_BACKOFF ** attempt
            time.sleep(sleep_time)

    logger.error(f"scrape_foreign_flow: {ticker} {date_str} gagal setelah {MAX_RETRIES} retry")
    return None


def scrape_foreign_flow_bulk(
    tickers: list[str],
    target_date: Optional[date] = None,
) -> pd.DataFrame:
    """Scrape foreign flow untuk banyak ticker sekaligus.

    Args:
        tickers: List kode saham IDX
        target_date: Tanggal data (default: hari ini)

    Returns:
        DataFrame dengan kolom foreign flow untuk semua ticker.
    """
    if target_date is None:
        target_date = date.today()

    results = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.debug(f"scrape_foreign_flow_bulk: [{i}/{total}] {ticker}")
        row = scrape_foreign_flow(ticker, target_date)
        if row:
            results.append(row)
        time.sleep(RATE_LIMIT_SEC)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    logger.info(
        f"scrape_foreign_flow_bulk: selesai {len(results)}/{total} ticker"
    )
    return df


def compute_foreign_trend(
    ticker: str,
    foreign_flow_history: pd.DataFrame,
) -> dict:
    """Hitung tren foreign flow 5 hari dan 20 hari dari historis.

    Args:
        ticker: Kode saham IDX
        foreign_flow_history: DataFrame historis foreign_flow dari Supabase,
                               sudah difilter untuk ticker ini.

    Returns:
        Dict: {
            "foreign_net_5d": float,   # total net 5 hari terakhir
            "foreign_net_20d": float,  # total net 20 hari terakhir
            "consecutive_buy": int,    # hari berturut-turut asing net buy
            "trend": str,              # "AKUMULASI", "DISTRIBUSI", "NETRAL"
        }
    """
    default = {
        "foreign_net_5d": 0.0,
        "foreign_net_20d": 0.0,
        "consecutive_buy": 0,
        "trend": "NETRAL",
    }

    if foreign_flow_history.empty:
        return default

    df = foreign_flow_history.sort_values("date", ascending=False).reset_index(drop=True)

    net_5d = float(df.head(5)["foreign_net"].sum()) if len(df) >= 1 else 0.0
    net_20d = float(df.head(20)["foreign_net"].sum()) if len(df) >= 1 else 0.0

    # Hitung hari berturut-turut net buy
    consecutive = 0
    for net in df["foreign_net"]:
        if net > 0:
            consecutive += 1
        else:
            break

    # Tentukan tren
    if net_5d > 0 and consecutive >= 3:
        trend = "AKUMULASI"
    elif net_5d < 0 and net_20d < 0:
        trend = "DISTRIBUSI"
    else:
        trend = "NETRAL"

    return {
        "foreign_net_5d": net_5d,
        "foreign_net_20d": net_20d,
        "consecutive_buy": consecutive,
        "trend": trend,
    }
