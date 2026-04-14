"""
health_check.py — Validasi koneksi semua services.

Jalankan sebelum deploy atau saat debugging untuk memastikan
semua service dapat diakses.

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --verbose
"""

import argparse
import logging
import sys
from datetime import datetime

# Pastikan root project di sys.path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings, configure_logging

logger = logging.getLogger(__name__)

STATUS_OK = "[OK]  "
STATUS_FAIL = "[FAIL]"
STATUS_WARN = "[WARN]"


def check_env_vars() -> tuple[str, str]:
    """Cek semua env vars wajib sudah diisi.

    Returns:
        Tuple (status, detail)
    """
    missing = settings.validate_partial(
        "SUPABASE_URL", "SUPABASE_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
    )
    if missing:
        return STATUS_FAIL, f"Missing: {', '.join(missing)}"
    return STATUS_OK, "Semua env vars terkonfigurasi"


def check_supabase() -> tuple[str, str]:
    """Cek koneksi ke Supabase dengan query sederhana.

    Returns:
        Tuple (status, detail)
    """
    if not settings.supabase_url or not settings.supabase_key:
        return STATUS_WARN, "SUPABASE_URL atau SUPABASE_KEY tidak dikonfigurasi"

    try:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        # Query sederhana untuk test koneksi
        result = client.table("emiten_universe").select("ticker").limit(1).execute()
        count = len(result.data)
        return STATUS_OK, f"Koneksi OK. emiten_universe: {count} rows (query sample)"
    except Exception as exc:
        err = str(exc)
        if "relation" in err.lower() and "does not exist" in err.lower():
            return STATUS_WARN, "Koneksi OK tapi tabel belum dibuat — jalankan migration SQL"
        return STATUS_FAIL, f"Error: {err[:200]}"


def check_telegram() -> tuple[str, str]:
    """Cek koneksi Telegram Bot API.

    Returns:
        Tuple (status, detail)
    """
    if not settings.telegram_bot_token:
        return STATUS_WARN, "TELEGRAM_BOT_TOKEN tidak dikonfigurasi"

    try:
        import requests
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            bot_name = data["result"].get("username", "unknown")
            return STATUS_OK, f"Bot aktif: @{bot_name}"
        else:
            return STATUS_FAIL, f"API error: {data.get('description', 'unknown')}"
    except Exception as exc:
        return STATUS_FAIL, f"Error: {str(exc)[:200]}"


def check_yfinance() -> tuple[str, str]:
    """Cek koneksi yfinance dengan fetch satu ticker.

    Returns:
        Tuple (status, detail)
    """
    try:
        import yfinance as yf
        # BBCA adalah saham paling likuid di IDX — selalu tersedia
        ticker = yf.Ticker("BBCA.JK")
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist.empty:
            return STATUS_WARN, "yfinance OK tapi tidak ada data (weekend/holiday?)"
        last_date = hist.index[-1].strftime("%Y-%m-%d")
        last_close = hist["Close"].iloc[-1]
        return STATUS_OK, f"Data OK. BBCA.JK close terakhir: Rp{last_close:,.0f} ({last_date})"
    except Exception as exc:
        return STATUS_FAIL, f"Error: {str(exc)[:200]}"


def check_emiten_count() -> tuple[str, str]:
    """Cek berapa emiten sudah ada di database.

    Returns:
        Tuple (status, detail)
    """
    if not settings.supabase_url or not settings.supabase_key:
        return STATUS_WARN, "Supabase tidak dikonfigurasi"

    try:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        result = client.table("emiten_universe").select("ticker", count="exact").execute()
        count = result.count or len(result.data)
        if count == 0:
            return STATUS_WARN, "0 emiten — jalankan scripts/seed_universe.py"
        elif count < 50:
            return STATUS_WARN, f"{count} emiten — universe mungkin belum lengkap"
        return STATUS_OK, f"{count} emiten di database"
    except Exception as exc:
        return STATUS_FAIL, f"Error: {str(exc)[:200]}"


def check_stockbit_token() -> tuple[str, str]:
    """Cek apakah Stockbit token masih valid.

    Jika expired, kirim Telegram alert otomatis.

    Returns:
        Tuple (status, detail)
    """
    token = settings.stockbit_token
    if not token:
        return STATUS_WARN, "STOCKBIT_TOKEN tidak dikonfigurasi di .env"

    try:
        from data.scrapers.broksum import check_stockbit_token as _check_token
        valid = _check_token(token)
        if valid:
            preview = token[:30] + "..."
            return STATUS_OK, f"Token valid ({preview})"
        else:
            # Kirim Telegram alert
            try:
                from output.telegram_bot import send_stockbit_token_alert
                preview = token[7:27] + "..." if len(token) > 27 else token
                send_stockbit_token_alert(token_preview=preview)
                alert_sent = " — alert Telegram terkirim"
            except Exception:
                alert_sent = " — gagal kirim alert Telegram"
            return STATUS_FAIL, f"Token expired atau invalid{alert_sent}"
    except Exception as exc:
        return STATUS_FAIL, f"Error saat cek token: {str(exc)[:200]}"


def check_price_data() -> tuple[str, str]:
    """Cek apakah ada data historis di tabel price_data.

    Returns:
        Tuple (status, detail)
    """
    if not settings.supabase_url or not settings.supabase_key:
        return STATUS_WARN, "Supabase tidak dikonfigurasi"

    try:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        result = (
            client.table("price_data")
            .select("date, ticker", count="exact")
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        total = result.count or 0
        if total == 0:
            return STATUS_WARN, "Tidak ada data price — jalankan scripts/backfill_ohlcv.py"
        latest = result.data[0]["date"] if result.data else "?"
        return STATUS_OK, f"{total} rows total. Data terbaru: {latest}"
    except Exception as exc:
        return STATUS_FAIL, f"Error: {str(exc)[:200]}"


def run_health_check(verbose: bool = False) -> bool:
    """Jalankan semua health checks dan print hasilnya.

    Args:
        verbose: Jika True, tampilkan detail lebih banyak.

    Returns:
        True jika semua critical checks passed.
    """
    print(f"\n{'='*60}")
    print(f"  WhaleDet IDX — Health Check")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    checks = [
        ("ENV VARS", check_env_vars),
        ("SUPABASE", check_supabase),
        ("TELEGRAM", check_telegram),
        ("STOCKBIT TOKEN", check_stockbit_token),
        ("YFINANCE", check_yfinance),
        ("EMITEN COUNT", check_emiten_count),
        ("PRICE DATA", check_price_data),
    ]

    all_ok = True
    results = []

    for name, check_fn in checks:
        try:
            status, detail = check_fn()
        except Exception as exc:
            status = STATUS_FAIL
            detail = f"Check error: {exc}"

        results.append((name, status, detail))
        if STATUS_FAIL in status:
            all_ok = False

    # Print results
    for name, status, detail in results:
        print(f"  {status}  {name:<20} {detail}")

    print(f"\n{'='*60}")
    if all_ok:
        print("  SEMUA CHECK: PASSED")
    else:
        print("  ADA CHECK YANG GAGAL -- lihat detail di atas")
    print(f"{'='*60}\n")

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="WhaleDet Health Check")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    configure_logging(debug=args.verbose)

    ok = run_health_check(verbose=args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
