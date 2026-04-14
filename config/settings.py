"""
settings.py — Load dan validasi semua environment variables.

Semua modul lain harus import dari sini, bukan langsung dari os.environ.
"""

import os
import logging
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """Konfigurasi aplikasi, diload dari environment variables."""

    # Supabase
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_KEY", ""))

    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))

    # Pipeline behavior
    dry_run: bool = False
    debug: bool = False

    # Stockbit
    stockbit_token: str = field(default_factory=lambda: os.environ.get("STOCKBIT_TOKEN", ""))

    # Scraping
    request_delay_sec: float = 1.0          # jeda minimum antar request
    max_retries: int = 3                    # max retry per request
    batch_size_yfinance: int = 50           # max ticker per batch yfinance call

    # Feature engineering
    volume_zscore_window: int = 20          # rolling window untuk z-score (Tier A & B)
    volume_zscore_window_tier_c: int = 60   # rolling window untuk z-score (Tier C)

    # Scoring
    min_score_for_alert: float = 50.0       # skor minimum untuk masuk alert
    top_n_signals: int = 10                 # max sinyal dikirim per Telegram message

    def validate(self) -> None:
        """Validasi semua env vars wajib ada. Raise ValueError jika tidak."""
        missing = []
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_KEY": self.supabase_key,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
        }
        for name, value in required.items():
            if not value:
                missing.append(name)

        if missing:
            raise ValueError(
                f"Environment variables berikut wajib diisi: {', '.join(missing)}\n"
                f"Salin .env.example ke .env dan isi nilainya."
            )

    def validate_partial(self, *keys: str) -> list[str]:
        """Validasi subset keys, return list keys yang missing (untuk health check)."""
        mapping = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_KEY": self.supabase_key,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
        }
        return [k for k in keys if not mapping.get(k, "")]


# Singleton — import ini dari modul lain
settings = Settings()


def configure_logging(debug: bool = False) -> None:
    """Setup logging format dan level.

    Args:
        debug: Jika True, set level ke DEBUG. Default INFO.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
