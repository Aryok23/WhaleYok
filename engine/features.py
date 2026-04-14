"""
features.py — Feature engineering dari data OHLCV.

Semua fungsi menerima DataFrame dan return Series atau DataFrame.
Tidak ada side effects, tidak ada database calls.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Threshold volume z-score untuk interpretasi
ZSCORE_THRESHOLDS = {
    "extreme": 5.0,
    "strong": 3.0,
    "moderate": 2.0,
    "slight": 1.0,
}


def compute_volume_zscore(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Hitung rolling z-score volume untuk DataFrame single ticker.

    Z-score mengukur berapa standar deviasi volume hari ini
    dari rata-rata rolling N hari.

    Args:
        df: DataFrame dengan kolom 'volume', diurutkan ascending by date.
        window: Rolling window dalam hari (default 20).

    Returns:
        pd.Series z-score dengan index sama seperti df.
        NaN untuk baris pertama di mana window belum cukup.
    """
    if "volume" not in df.columns:
        logger.warning("compute_volume_zscore: kolom 'volume' tidak ditemukan")
        return pd.Series(dtype=float)

    vol = df["volume"].astype(float)

    rolling_mean = vol.rolling(window=window, min_periods=max(window // 2, 5)).mean()
    rolling_std = vol.rolling(window=window, min_periods=max(window // 2, 5)).std()

    # Hindari division by zero — kalau std = 0, semua volume sama, zscore = 0
    rolling_std = rolling_std.replace(0, np.nan)

    zscore = (vol - rolling_mean) / rolling_std
    return zscore


def compute_price_change(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
    """Hitung perubahan harga untuk beberapa periode.

    Validasi date gap: jika jarak antar baris > batas kalender wajar,
    price_change di-set NaN agar tidak membandingkan harga yang berselisih
    berminggu-minggu seolah perubahan 1 hari.

    Batas: p=1 → max 7 hari, p=3 → max 14 hari, p=5 → max 21 hari.
    (Buffer untuk libur panjang/weekend panjang.)

    Args:
        df: DataFrame dengan kolom 'close' dan 'date', sorted ascending by date.
        periods: List jumlah hari lookback. Default [1, 3, 5].

    Returns:
        DataFrame dengan kolom price_change_1d, price_change_3d, price_change_5d.
        Nilai fraksi desimal (0.05 = +5%). NaN jika data gap terlalu besar.
    """
    if periods is None:
        periods = [1, 3, 5]

    if "close" not in df.columns:
        logger.warning("compute_price_change: kolom 'close' tidak ditemukan")
        return pd.DataFrame()

    close = df["close"].astype(float)
    result = pd.DataFrame(index=df.index)

    has_dates = "date" in df.columns
    if has_dates:
        dates = pd.to_datetime(df["date"]).reset_index(drop=True)

    for p in periods:
        col_name = f"price_change_{p}d"
        changes = close.pct_change(periods=p)

        # Invalidasi baris yang date gap-nya terlalu besar
        if has_dates:
            max_gap = p * 7  # 7 hari kalender per periode trading
            for i in range(p, len(df)):
                gap_days = (dates.iloc[i] - dates.iloc[i - p]).days
                if gap_days > max_gap:
                    changes.iloc[i] = np.nan

        result[col_name] = changes

    return result


def classify_volume_price_scenario(zscore: float, price_change: float) -> str:
    """Klasifikasi skenario berdasarkan kombinasi volume z-score dan price change.

    Args:
        zscore: Volume z-score hari ini
        price_change: Perubahan harga dalam fraksi (misal 0.03 = +3%)

    Returns:
        Salah satu dari: "ACCUMULATION", "BREAKOUT", "DISTRIBUTION", "PANIC", "NORMAL"
    """
    if zscore < ZSCORE_THRESHOLDS["slight"]:
        return "NORMAL"

    if price_change > 0.05:
        # Volume tinggi + harga naik besar → breakout atau late stage
        return "BREAKOUT"
    elif price_change >= -0.01:
        # Volume tinggi + harga flat atau naik tipis → akumulasi
        return "ACCUMULATION"
    elif price_change < -0.02:
        if zscore > ZSCORE_THRESHOLDS["strong"]:
            # Volume ekstrem + harga turun tajam → panic selling atau distribusi
            return "PANIC"
        else:
            # Volume tinggi + harga turun moderat → distribusi
            return "DISTRIBUTION"
    else:
        return "ACCUMULATION"


def compute_features_for_ticker(
    history_df: pd.DataFrame,
    window: int = 20,
) -> dict | None:
    """Hitung semua features untuk satu ticker dari historis OHLCV-nya.

    Args:
        history_df: DataFrame OHLCV satu ticker, sorted ascending by date.
                    Minimal harus punya kolom: date, ticker, close, volume.
        window: Rolling window z-score.

    Returns:
        Dict berisi semua features untuk hari terakhir di df.
        None jika data tidak cukup atau invalid.
    """
    if history_df.empty:
        return None

    required_cols = {"close", "volume"}
    if not required_cols.issubset(history_df.columns):
        logger.warning(
            f"compute_features_for_ticker: kolom wajib tidak ada: "
            f"{required_cols - set(history_df.columns)}"
        )
        return None

    df = history_df.sort_values("date").reset_index(drop=True)

    if len(df) < 5:
        logger.warning(
            f"compute_features_for_ticker: data terlalu sedikit ({len(df)} rows), "
            f"minimal 5 baris. Ticker: {df['ticker'].iloc[-1] if 'ticker' in df.columns else '?'}"
        )
        return None

    # Hitung z-score
    zscore_series = compute_volume_zscore(df, window=window)
    current_zscore = zscore_series.iloc[-1] if not zscore_series.empty else np.nan

    # Hitung price change
    price_changes = compute_price_change(df, periods=[1, 3, 5])
    price_change_1d = price_changes["price_change_1d"].iloc[-1] if not price_changes.empty else np.nan
    price_change_3d = price_changes["price_change_3d"].iloc[-1] if not price_changes.empty else np.nan
    price_change_5d = price_changes["price_change_5d"].iloc[-1] if not price_changes.empty else np.nan

    last_row = df.iloc[-1]
    volume_today = float(last_row.get("volume", 0))

    # Baseline volume (rolling mean)
    vol_series = df["volume"].astype(float)
    rolling_mean = vol_series.rolling(window=window, min_periods=max(window // 2, 5)).mean()
    baseline_volume = rolling_mean.iloc[-1] if not rolling_mean.empty else np.nan

    # Klasifikasi skenario
    if not (np.isnan(current_zscore) or np.isnan(price_change_1d)):
        scenario = classify_volume_price_scenario(current_zscore, price_change_1d)
    else:
        scenario = "NORMAL"

    ticker = df["ticker"].iloc[-1] if "ticker" in df.columns else ""

    return {
        "ticker": ticker,
        "date": last_row.get("date"),
        "close": float(last_row.get("close", 0)),
        "volume_today": volume_today,
        "volume_baseline_20d": float(baseline_volume) if not np.isnan(baseline_volume) else None,
        "volume_ratio": float(volume_today / baseline_volume) if baseline_volume and not np.isnan(baseline_volume) and baseline_volume > 0 else None,
        "volume_zscore": float(current_zscore) if not np.isnan(current_zscore) else None,
        "price_change_1d": float(price_change_1d) if not np.isnan(price_change_1d) else None,
        "price_change_3d": float(price_change_3d) if not np.isnan(price_change_3d) else None,
        "price_change_5d": float(price_change_5d) if not np.isnan(price_change_5d) else None,
        "scenario": scenario,
    }
