"""
broksum.py — Scraper broker summary harian.

Sumber utama: Stockbit (exodus.stockbit.com) — punya data buy/sell per broker.
  Endpoint: GET /order-trade/broker/distribution
  Auth: Bearer token dari STOCKBIT_TOKEN di .env
  Data: top 12 buyer + top 12 seller per hari per saham (value & volume)

Fallback: IDX.co.id — hanya total per broker, tidak ada buy/sell split.
  (Dipertahankan untuk referensi, tidak digunakan di pipeline utama)

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

STOCKBIT_BROKDIST_URL = "https://exodus.stockbit.com/order-trade/broker/distribution"

STOCKBIT_TYPE_MAP = {
    "Asing": "ASING",
    "Pemerintah": "INSTITUSI",
    "Lokal": "RETAIL",
}

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


def scrape_broksum_stockbit(
    ticker: str,
    target_date: date,
    token: str,
) -> pd.DataFrame:
    """Scrape broker distribution untuk satu ticker satu hari dari Stockbit.

    Endpoint: GET https://exodus.stockbit.com/order-trade/broker/distribution
    Auth: Bearer token dari exodus.stockbit.com (valid ~24 jam).

    Data yang tersedia: top 12 buyer + top 12 seller per hari (by value & by volume).
    freq_buy / freq_sell tidak tersedia — diisi 0.

    Args:
        ticker: Kode saham IDX (uppercase, tanpa .JK)
        target_date: Tanggal data
        token: Bearer token Stockbit (format "Bearer eyJ...")

    Returns:
        DataFrame broker_summary. Kosong jika gagal atau tidak ada data.
    """
    date_str = target_date.isoformat()
    headers = {
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

    for data_type in ("BROKER_DISTRIBUTION_DATA_TYPE_VALUE", "BROKER_DISTRIBUTION_DATA_TYPE_VOLUME"):
        pass  # both fetched in one call below

    params = {
        "symbol": ticker,
        "from": date_str,
        "to": date_str,
        "investor_type": "INVESTOR_TYPE_ALL",
        "market_board": "MARKET_TYPE_REGULER",
        "data_type": "BROKER_DISTRIBUTION_DATA_TYPE_VALUE",
        "date": "",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                STOCKBIT_BROKDIST_URL,
                params=params,
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 401:
                logger.error(
                    f"scrape_broksum_stockbit: {ticker} {date_str} — 401 Unauthorized. "
                    "Token expired atau tidak valid. Update STOCKBIT_TOKEN di .env"
                )
                return pd.DataFrame()

            if resp.status_code == 404:
                logger.warning(f"scrape_broksum_stockbit: {ticker} {date_str} — 404 not found")
                return pd.DataFrame()

            resp.raise_for_status()
            payload = resp.json()

            inner = payload.get("data", {})
            if not inner:
                logger.warning(f"scrape_broksum_stockbit: {ticker} {date_str} — respons kosong")
                return pd.DataFrame()

            by_value = inner.get("by_value", {})
            by_volume = inner.get("by_volume", {})

            # Kumpulkan buy_value dan sell_value per broker
            broker_data: dict[str, dict] = {}

            def _add_entry(entries: list, field: str, side: str) -> None:
                """Isi buy/sell value/volume dari top_broker_buy/sell list."""
                for entry in entries:
                    detail = entry.get("detail", {})
                    code = str(detail.get("code", "")).strip().upper()
                    if not code:
                        continue
                    broker_type = STOCKBIT_TYPE_MAP.get(
                        detail.get("type", ""), "RETAIL"
                    )
                    amount = float(detail.get("amount", 0) or 0)

                    if code not in broker_data:
                        broker_data[code] = {
                            "category": broker_type,
                            "buy_value": 0,
                            "sell_value": 0,
                            "buy_volume": 0,
                            "sell_volume": 0,
                        }
                    broker_data[code][f"{side}_{field}"] = amount
                    # Pertahankan category dari data yang ada
                    if broker_data[code]["category"] == "RETAIL" and broker_type != "RETAIL":
                        broker_data[code]["category"] = broker_type

            _add_entry(by_value.get("top_broker_buy", []), "value", "buy")
            _add_entry(by_value.get("top_broker_sell", []), "value", "sell")
            _add_entry(by_volume.get("top_broker_buy", []), "volume", "buy")
            _add_entry(by_volume.get("top_broker_sell", []), "volume", "sell")

            if not broker_data:
                logger.warning(f"scrape_broksum_stockbit: {ticker} {date_str} — tidak ada broker")
                return pd.DataFrame()

            records = []
            for broker_code, vals in broker_data.items():
                records.append({
                    "date": target_date.isoformat(),
                    "ticker": ticker,
                    "broker_code": broker_code,
                    "buy_value": int(vals["buy_value"]),
                    "sell_value": int(vals["sell_value"]),
                    "buy_volume": int(vals["buy_volume"]),
                    "sell_volume": int(vals["sell_volume"]),
                    "freq_buy": 0,
                    "freq_sell": 0,
                    "category": vals["category"],
                })

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            logger.debug(
                f"scrape_broksum_stockbit: {ticker} {date_str} — {len(df)} broker rows"
            )
            return df

        except requests.Timeout:
            logger.warning(
                f"scrape_broksum_stockbit: timeout {ticker} attempt {attempt}/{MAX_RETRIES}"
            )
        except requests.HTTPError as exc:
            logger.warning(
                f"scrape_broksum_stockbit: HTTP error {ticker}: {exc} attempt {attempt}/{MAX_RETRIES}"
            )
        except (ValueError, KeyError) as exc:
            logger.error(f"scrape_broksum_stockbit: parse error {ticker}: {exc}")
            return pd.DataFrame()
        except requests.RequestException as exc:
            logger.warning(
                f"scrape_broksum_stockbit: request error {ticker}: {exc} attempt {attempt}/{MAX_RETRIES}"
            )

        if attempt < MAX_RETRIES:
            sleep_time = RETRY_BACKOFF ** attempt
            logger.debug(f"scrape_broksum_stockbit: retry {attempt} in {sleep_time:.1f}s")
            time.sleep(sleep_time)

    logger.error(
        f"scrape_broksum_stockbit: {ticker} {date_str} gagal setelah {MAX_RETRIES} retry"
    )
    return pd.DataFrame()


def check_stockbit_token(token: str) -> bool:
    """Validasi apakah Stockbit token masih aktif dengan satu request ringan.

    Args:
        token: Bearer token Stockbit

    Returns:
        True jika token valid, False jika expired/invalid.
    """
    if not token:
        return False

    headers = {
        "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }
    # Gunakan ticker paling likuid, tanggal kemarin (hari kerja terakhir)
    from datetime import timedelta
    check_date = date.today() - timedelta(days=1)
    # Mundur ke hari Jumat jika weekend
    while check_date.weekday() >= 5:
        check_date -= timedelta(days=1)

    params = {
        "symbol": "BBCA",
        "from": check_date.isoformat(),
        "to": check_date.isoformat(),
        "investor_type": "INVESTOR_TYPE_ALL",
        "market_board": "MARKET_TYPE_REGULER",
        "data_type": "BROKER_DISTRIBUTION_DATA_TYPE_VALUE",
        "date": "",
    }

    try:
        resp = requests.get(
            STOCKBIT_BROKDIST_URL,
            params=params,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 401:
            logger.warning("check_stockbit_token: token expired (401)")
            return False
        if resp.status_code == 200:
            return True
        logger.warning(f"check_stockbit_token: status {resp.status_code}")
        return False
    except requests.RequestException as exc:
        logger.warning(f"check_stockbit_token: request error: {exc}")
        return False


def scrape_broksum_stockbit_bulk(
    tickers: list[str],
    target_date: date,
    token: str,
) -> pd.DataFrame:
    """Scrape broker distribution untuk banyak ticker sekaligus via Stockbit.

    Args:
        tickers: List kode saham IDX
        target_date: Tanggal data
        token: Bearer token Stockbit

    Returns:
        DataFrame gabungan semua ticker. Kosong jika semua gagal.
    """
    all_dfs = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.debug(f"scrape_broksum_stockbit_bulk: [{i}/{total}] {ticker}")
        df = scrape_broksum_stockbit(ticker, target_date, token)
        if not df.empty:
            all_dfs.append(df)
        time.sleep(RATE_LIMIT_SEC)

    if not all_dfs:
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        f"scrape_broksum_stockbit_bulk: selesai {len(all_dfs)}/{total} ticker, "
        f"{len(result)} rows total"
    )
    return result


def compute_broker_net_by_category(broksum_df: pd.DataFrame) -> dict:
    """Hitung total net value per kategori broker untuk satu ticker.

    Args:
        broksum_df: Output dari scrape_broksum_stockbit() untuk satu ticker.
                    Kolom wajib: buy_value, sell_value, category.
                    net_value tidak wajib ada (dihitung otomatis jika tidak ada).

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

    df = broksum_df.copy()
    # Hitung net_value dari buy-sell jika kolom belum ada (DB GENERATED column
    # tidak ikut di-return oleh scraper)
    if "net_value" not in df.columns:
        df["net_value"] = df["buy_value"] - df["sell_value"]

    asing_net = float(df[df["category"] == "ASING"]["net_value"].sum())
    institusi_net = float(df[df["category"] == "INSTITUSI"]["net_value"].sum())
    retail_net = float(df[df["category"] == "RETAIL"]["net_value"].sum())
    smart_money_net = asing_net + institusi_net

    return {
        "asing_net": asing_net,
        "institusi_net": institusi_net,
        "retail_net": retail_net,
        "asing_dominan": asing_net > 0 and asing_net >= institusi_net,
        "smart_money_net": smart_money_net,
    }
