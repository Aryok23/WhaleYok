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


def _fmt_score_bar(score: float | None) -> str:
    """Buat visual bar sederhana untuk score 0-100.

    Contoh: score 80 → '████░░ 80'
    """
    if score is None:
        return "N/A"
    filled = round(score / 20)  # 0-5 blok
    bar = "█" * filled + "░" * (5 - filled)
    return f"{bar} {score:.0f}"


def _format_signal_entry(rank: int, signal: dict) -> str:
    """Format satu sinyal menjadi teks HTML untuk Telegram dengan breakdown per faktor.

    Args:
        rank: Nomor urut (1-based)
        signal: Dict sinyal dari scorer.py

    Returns:
        String HTML untuk satu sinyal.
    """
    ticker = signal.get("ticker", "?")
    score = signal.get("composite_score", 0)
    signal_type = signal.get("signal_type", "MONITOR")
    volume_score = signal.get("volume_score")
    broker_score = signal.get("broker_score")
    foreign_score = signal.get("foreign_score")
    conflict = signal.get("conflict")
    evidence = signal.get("evidence_json", {}) or {}

    emoji = SIGNAL_EMOJI.get(signal_type, "⚪")
    action = SIGNAL_ACTION.get(signal_type, "Monitor")

    # Volume detail
    vol_ev = evidence.get("volume", {})
    vol_ratio = vol_ev.get("ratio")
    zscore = vol_ev.get("zscore")
    vol_detail = ""
    if vol_ratio:
        vol_detail = f" ({vol_ratio:.1f}x, z={zscore:.1f})" if zscore else f" ({vol_ratio:.1f}x)"

    # Price
    price_ev = evidence.get("price", {})
    price_change = price_ev.get("change_1d")
    close_price = price_ev.get("close")
    if close_price:
        close_fmt = f"Rp {int(close_price):,}".replace(",", ".")
        if price_change is not None:
            sign = "+" if price_change >= 0 else ""
            price_str = f"  💰 Harga : {close_fmt} ({sign}{price_change * 100:.1f}%)"
        else:
            price_str = f"  💰 Harga : {close_fmt}"
    else:
        price_str = ""

    # Broker detail
    broker_ev = evidence.get("broker", {})
    broker_detail = ""
    if broker_score is not None and broker_ev:
        asing_net = broker_ev.get("asing_net", 0)
        institusi_net = broker_ev.get("institusi_net", 0)
        sign_a = "+" if asing_net >= 0 else ""
        sign_i = "+" if institusi_net >= 0 else ""
        broker_detail = (
            f" (A:{sign_a}{asing_net/1e6:.0f}M I:{sign_i}{institusi_net/1e6:.0f}M)"
        )

    # Foreign detail
    foreign_ev = evidence.get("foreign", {})
    foreign_detail = ""
    if foreign_score is not None and foreign_ev:
        f_net = foreign_ev.get("foreign_net", 0)
        f_consec = foreign_ev.get("consecutive_buy", 0)
        f_trend = foreign_ev.get("trend", "")
        sign_f = "+" if f_net >= 0 else ""
        consec_str = f" {f_consec}hr berturut" if f_consec >= 2 else ""
        foreign_detail = f" ({sign_f}{f_net/1e6:.0f}M{consec_str})"

    # Scenario
    scenario = evidence.get("scenario", "")

    # Build lines
    header = f"<b>{rank}. {ticker}</b> {emoji}  Final: <b>{score:.0f}</b>"
    if scenario and scenario != "NORMAL":
        header += f"  [{scenario}]"

    lines = [header]

    # Breakdown faktor
    lines.append(f"   📊 Volume : {_fmt_score_bar(volume_score)}{vol_detail}")

    if broker_score is not None:
        lines.append(f"   🏦 Broker : {_fmt_score_bar(broker_score)}{broker_detail}")
    else:
        lines.append(f"   🏦 Broker : —")

    if foreign_score is not None:
        lines.append(f"   🌏 Asing  : {_fmt_score_bar(foreign_score)}{foreign_detail}")
    else:
        lines.append(f"   🌏 Asing  : —")

    if price_str:
        lines.append(f"  {price_str}")

    # Conflict warning
    if conflict:
        lines.append(f"   ⚠️ <i>Sinyal konflik — cek manual</i>")

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


def send_stockbit_token_alert(token_preview: str = "") -> bool:
    """Kirim alert bahwa Stockbit token expired dan perlu diperbarui.

    Args:
        token_preview: Potongan awal token lama (untuk identifikasi)

    Returns:
        True jika berhasil dikirim.
    """
    preview = f"\nToken lama: <code>{token_preview}</code>" if token_preview else ""
    msg = (
        f"🔑 <b>WhaleDet — STOCKBIT_TOKEN Expired</b>\n\n"
        f"Token Stockbit tidak valid atau sudah expired.\n"
        f"Broksum hari ini <b>tidak dapat diambil</b> sampai token diperbarui.{preview}\n\n"
        f"<b>Cara update:</b>\n"
        f"1. Buka exodus.stockbit.com di browser\n"
        f"2. Login, buka DevTools → Network\n"
        f"3. Klik saham apa saja, cari request ke <code>/broker/distribution</code>\n"
        f"4. Copy nilai <code>Authorization</code> header\n"
        f"5. Update <code>STOCKBIT_TOKEN</code> di <code>.env</code>\n\n"
        f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M WIB')}"
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
