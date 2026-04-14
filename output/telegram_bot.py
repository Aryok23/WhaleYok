"""
telegram_bot.py — Kirim alert ke Telegram.

Menggunakan requests (bukan python-telegram-bot) untuk keep dependency minimal.
Handle error gracefully — jika Telegram down, log warning dan lanjutkan.
"""

import logging
from datetime import date, datetime

import requests

from config.settings import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
SEND_TIMEOUT_SEC = 10

# Emoji berdasarkan signal type
SIGNAL_EMOJI = {
    "STRONG_BUY": "🟢🟢",
    "WATCH_BUY": "🟢",
    "MONITOR": "🟡",
    "NEUTRAL": "⚪",
    "DISTRIBUSI": "🔴",
}

# Label aksi berdasarkan signal type
SIGNAL_ACTION = {
    "STRONG_BUY": "⚡ Strong Buy Signal",
    "WATCH_BUY": "👀 Watch & Accumulate",
    "MONITOR": "📋 Masuk Watchlist",
    "NEUTRAL": "➖ Netral",
    "DISTRIBUSI": "⚠️ Distribusi Warning",
}


def _send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Kirim pesan ke Telegram.

    Args:
        text: Teks pesan (support HTML formatting)
        parse_mode: "HTML" atau "Markdown"

    Returns:
        True jika berhasil, False jika gagal.
    """
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        logger.error("Telegram token atau chat_id tidak dikonfigurasi")
        return False

    url = TELEGRAM_API_BASE.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=SEND_TIMEOUT_SEC)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            logger.warning(f"Telegram API error: {result.get('description', 'unknown')}")
            return False
        return True
    except requests.Timeout:
        logger.warning("Telegram sendMessage timeout — akan dicoba lagi di run berikutnya")
        return False
    except requests.HTTPError as exc:
        logger.error(f"Telegram HTTP error: {exc}")
        return False
    except Exception as exc:
        logger.error(f"Telegram unexpected error: {exc}")
        return False


def _format_signal_entry(rank: int, signal: dict) -> str:
    """Format satu sinyal menjadi teks HTML untuk Telegram.

    Args:
        rank: Nomor urut (1-based)
        signal: Dict sinyal dari scorer.py

    Returns:
        String HTML untuk satu sinyal.
    """
    ticker = signal.get("ticker", "?")
    score = signal.get("composite_score", 0)
    signal_type = signal.get("signal_type", "MONITOR")
    volume_zscore = signal.get("volume_zscore")
    evidence = signal.get("evidence_json", {})

    emoji = SIGNAL_EMOJI.get(signal_type, "⚪")
    action = SIGNAL_ACTION.get(signal_type, "Monitor")

    # Volume info
    vol_evidence = evidence.get("volume", {}) if evidence else {}
    vol_ratio = vol_evidence.get("ratio")
    vol_ratio_str = f"{vol_ratio:.1f}x" if vol_ratio else "N/A"

    zscore_str = f"{volume_zscore:.2f}" if volume_zscore is not None else "N/A"

    # Price info
    price_evidence = evidence.get("price", {}) if evidence else {}
    price_change = price_evidence.get("change_1d")
    price_str = ""
    if price_change is not None:
        sign = "+" if price_change >= 0 else ""
        price_str = f" | Harga: {sign}{price_change * 100:.1f}%"

    scenario = evidence.get("scenario", "") if evidence else ""
    scenario_str = f" | {scenario}" if scenario and scenario != "NORMAL" else ""

    lines = [
        f"<b>{rank}. {ticker}</b> {emoji} Score: <b>{score:.0f}</b>",
        f"   📊 Vol: {vol_ratio_str} baseline | Z-score: {zscore_str}{price_str}",
    ]
    if scenario_str:
        lines.append(f"   📌 {scenario}")
    lines.append(f"   → {action}")

    return "\n".join(lines)


def _format_eod_message(
    signals: list[dict],
    target_date: date | None = None,
    total_scanned: int = 0,
) -> str:
    """Format pesan lengkap EOD alert.

    Args:
        signals: List sinyal (sudah diurutkan, max 10 per pesan)
        target_date: Tanggal scan
        total_scanned: Berapa emiten total yang diproses

    Returns:
        String HTML pesan Telegram.
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%d %b %Y")
    time_str = datetime.now().strftime("%H:%M WIB")

    header = (
        f"🐋 <b>WhaleDet IDX — {date_str} {time_str}</b>\n"
        f"🔍 Scan: {total_scanned} emiten\n\n"
        f"🟢 <b>TOP SIGNALS HARI INI:</b>"
    )

    if not signals:
        body = "\n\n<i>Tidak ada sinyal signifikan hari ini.</i>"
    else:
        entries = []
        for i, sig in enumerate(signals, 1):
            entries.append(_format_signal_entry(i, sig))
        body = "\n\n" + "\n\n".join(entries)

    footer = (
        "\n\n⚠️ <i>Disclaimer: Ini bukan rekomendasi investasi.\n"
        "DYOR sebelum mengambil posisi.</i>"
    )

    return header + body + footer


def send_eod_alert(
    signals: list[dict],
    target_date: date | None = None,
    total_scanned: int = 0,
    dry_run: bool = False,
) -> bool:
    """Kirim EOD alert ke Telegram.

    Jika sinyal > 10, dipecah menjadi beberapa pesan.

    Args:
        signals: List dict sinyal dari scorer.py, sudah diurutkan
        target_date: Tanggal scan (default: hari ini)
        total_scanned: Total emiten yang diproses
        dry_run: Jika True, hanya log pesan tanpa kirim

    Returns:
        True jika semua pesan berhasil dikirim.
    """
    if not signals:
        logger.info("send_eod_alert: tidak ada sinyal untuk dikirim")
        # Tetap kirim notifikasi kosong
        msg = _format_eod_message([], target_date, total_scanned)
        if dry_run:
            logger.info(f"[DRY RUN] Pesan Telegram:\n{msg}")
            return True
        return _send_message(msg)

    max_per_message = settings.top_n_signals  # default 10

    all_ok = True
    for i in range(0, min(len(signals), max_per_message * 3), max_per_message):
        batch = signals[i : i + max_per_message]
        # Hanya kirim total_scanned di pesan pertama
        scanned = total_scanned if i == 0 else 0
        msg = _format_eod_message(batch, target_date, scanned)

        if dry_run:
            logger.info(f"[DRY RUN] Pesan Telegram batch {i // max_per_message + 1}:\n{msg}")
        else:
            ok = _send_message(msg)
            if not ok:
                logger.warning(f"Gagal kirim batch pesan Telegram ke-{i // max_per_message + 1}")
                all_ok = False

    return all_ok


def send_pipeline_failure_alert(error_message: str) -> bool:
    """Kirim notifikasi kegagalan pipeline ke Telegram.

    Dipanggil dari GitHub Actions 'on failure' step.

    Args:
        error_message: Pesan error singkat

    Returns:
        True jika berhasil.
    """
    msg = (
        f"⚠️ <b>WhaleDet Pipeline GAGAL</b>\n\n"
        f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Error: <code>{error_message[:500]}</code>\n\n"
        f"Cek GitHub Actions untuk detail lengkap."
    )
    return _send_message(msg)


def send_test_message() -> bool:
    """Kirim pesan test untuk verifikasi koneksi Telegram.

    Returns:
        True jika koneksi berhasil.
    """
    msg = (
        f"✅ <b>WhaleDet IDX — Test Connection</b>\n\n"
        f"Bot berjalan normal.\n"
        f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return _send_message(msg)
