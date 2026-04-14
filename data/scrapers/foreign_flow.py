"""
foreign_flow.py — Scraper foreign net buy/sell harian dari Stockbit.

Sumber utama: Stockbit (exodus.stockbit.com) — data foreign buy/sell per hari.
  Endpoint: GET /company-price-feed/historical/summary/{ticker}
  Auth: Bearer token dari STOCKBIT_TOKEN di .env
  Data: foreign_buy, foreign_sell, net_foreign per hari

IDX.co.id (GetForeignSummary) tidak digunakan — diblokir Cloudflare 403.

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

STOCKBIT_SUMMARY_URL = "https://exodus.stockbit.com/company-price-feed/historical/summary/{ticker}"

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
RATE_LIMIT_SEC = 1.0


def _stockbit_headers(token: str) -> dict:
    return {
        "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }


def scrape_foreign_flow(
    ticker: str,
    target_date: Optional[date] = None,
    token: str = "",
) -> Optional[dict]:
    """Scrape foreign net buy/sell untuk satu ticker satu hari dari Stockbit.

    Args:
        ticker: Kode saham IDX (uppercase, tanpa .JK)
        target_date: Tanggal data (default: hari ini)
        token: Bearer token Stockbit (dari settings.stockbit_token)

    Returns:
        Dict berisi data foreign flow, atau None jika gagal.
        Keys: ticker, date, foreign_buy, foreign_sell,
              foreign_buy_volume, foreign_sell_volume, _foreign_net
    """
    if target_date is None:
        target_date = date.today()

    if not token:
        from config.settings import settings
        token = settings.stockbit_token

    date_str = target_date.isoformat()
    url = STOCKBIT_SUMMARY_URL.format(ticker=ticker)
    params = {
        "period": "HS_PERIOD_DAILY",
        "start_date": date_str,
        "end_date": date_str,
        "limit": 5,
        "page": 1,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=_stockbit_headers(token),
                timeout=15,
            )

            if resp.status_code == 401:
                logger.error(
                    f"scrape_foreign_flow: {ticker} — 401 Unauthorized. "
                    "Token expired. Update STOCKBIT_TOKEN di .env"
                )
                return None

            if resp.status_code == 404:
                logger.warning(f"scrape_foreign_flow: {ticker} {date_str} — 404")
                return None

            resp.raise_for_status()
            payload = resp.json()

            rows = payload.get("data", {}).get("result", [])
            if not rows:
                logger.warning(f"scrape_foreign_flow: {ticker} {date_str} — data kosong")
                return None

            # Cari row yang sesuai tanggal
            row = next((r for r in rows if r.get("date") == date_str), None)
            if not row:
                logger.warning(
                    f"scrape_foreign_flow: {ticker} {date_str} — "
                    f"tanggal tidak ditemukan (rows: {[r.get('date') for r in rows]})"
                )
                return None

            try:
                foreign_buy = float(row.get("foreign_buy", 0) or 0)
                foreign_sell = float(row.get("foreign_sell", 0) or 0)
                net_foreign = float(row.get("net_foreign", 0) or 0)
            except (ValueError, TypeError) as exc:
                logger.error(f"scrape_foreign_flow: parse error {ticker}: {exc}")
                return None

            result = {
                "ticker": ticker,
                "date": date_str,
                "foreign_buy": int(foreign_buy),
                "foreign_sell": int(foreign_sell),
                # foreign_net adalah GENERATED column di DB — tidak diinsert
                # volume tidak tersedia dari endpoint ini — set 0
                "foreign_buy_volume": 0,
                "foreign_sell_volume": 0,
                # simpan net untuk scoring (tidak ditulis ke DB)
                "_foreign_net": net_foreign,
            }
            logger.debug(
                f"scrape_foreign_flow: {ticker} {date_str} "
                f"net={result['_foreign_net']:+.0f}"
            )
            return result

        except requests.Timeout:
            logger.warning(
                f"scrape_foreign_flow: timeout {ticker} attempt {attempt}/{MAX_RETRIES}"
            )
        except requests.HTTPError as exc:
            logger.warning(f"scrape_foreign_flow: HTTP error {ticker}: {exc}")
        except requests.RequestException as exc:
            logger.warning(f"scrape_foreign_flow: request error {ticker}: {exc}")

        if attempt < MAX_RETRIES:
            sleep_time = RETRY_BACKOFF ** attempt
            time.sleep(sleep_time)

    logger.error(
        f"scrape_foreign_flow: {ticker} {date_str} gagal setelah {MAX_RETRIES} retry"
    )
    return None


def scrape_foreign_flow_bulk(
    tickers: list[str],
    target_date: Optional[date] = None,
    token: str = "",
) -> pd.DataFrame:
    """Scrape foreign flow untuk banyak ticker sekaligus via Stockbit.

    Args:
        tickers: List kode saham IDX
        target_date: Tanggal data (default: hari ini)
        token: Bearer token Stockbit

    Returns:
        DataFrame dengan kolom foreign flow untuk semua ticker.
    """
    if target_date is None:
        target_date = date.today()

    if not token:
        from config.settings import settings
        token = settings.stockbit_token

    results = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.debug(f"scrape_foreign_flow_bulk: [{i}/{total}] {ticker}")
        row = scrape_foreign_flow(ticker, target_date, token=token)
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
