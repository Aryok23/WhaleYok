"""
test_features.py — Unit tests untuk engine/features.py.

Jalankan: pytest tests/ -v
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.features import (
    compute_price_change,
    compute_volume_zscore,
    classify_volume_price_scenario,
    compute_features_for_ticker,
)


def make_sample_df(
    n_days: int = 25,
    base_volume: int = 1_000_000,
    base_close: float = 1000.0,
    spike_day: int | None = None,
    spike_factor: float = 5.0,
) -> pd.DataFrame:
    """Buat DataFrame OHLCV sederhana untuk testing."""
    today = date.today()
    dates = [today - timedelta(days=n_days - 1 - i) for i in range(n_days)]

    volumes = [base_volume] * n_days
    closes = [base_close + i * 5 for i in range(n_days)]

    if spike_day is not None and 0 <= spike_day < n_days:
        volumes[spike_day] = int(base_volume * spike_factor)

    return pd.DataFrame({
        "date": dates,
        "ticker": "TEST",
        "open": [c - 10 for c in closes],
        "high": [c + 20 for c in closes],
        "low": [c - 20 for c in closes],
        "close": closes,
        "volume": volumes,
    })


class TestComputeVolumeZscore:
    def test_returns_series_same_length(self):
        df = make_sample_df(n_days=25)
        result = compute_volume_zscore(df, window=20)
        assert len(result) == len(df)

    def test_spike_has_high_zscore(self):
        """Hari dengan volume spike harus punya z-score tinggi."""
        df = make_sample_df(n_days=25, spike_day=24, spike_factor=10.0)
        result = compute_volume_zscore(df, window=20)
        # Z-score hari terakhir (spike) harus jauh di atas 0
        assert result.iloc[-1] > 3.0, f"Expected z-score > 3, got {result.iloc[-1]}"

    def test_normal_volume_near_zero_zscore(self):
        """Volume dengan sedikit variasi (bukan volume spike) → z-score kecil atau NaN."""
        import random
        random.seed(42)
        # Buat volume dengan sedikit noise (bukan konstan — std > 0)
        n = 25
        today = date.today()
        dates = [today - timedelta(days=n - 1 - i) for i in range(n)]
        base = 1_000_000
        volumes = [base + random.randint(-50_000, 50_000) for _ in range(n)]
        closes = [1000.0 + i for i in range(n)]
        df = pd.DataFrame({
            "date": dates,
            "ticker": "TEST",
            "close": closes,
            "volume": volumes,
        })
        result = compute_volume_zscore(df, window=20)
        last_zscore = result.iloc[-1]
        # Volume terakhir tidak spike → z-score harus kecil (bukan > 3)
        if not pd.isna(last_zscore):
            assert abs(last_zscore) < 3.0, f"Expected |z-score| < 3, got {last_zscore}"

    def test_missing_volume_column(self):
        """Kolom volume tidak ada → return empty Series."""
        df = pd.DataFrame({"date": [date.today()], "close": [1000.0]})
        result = compute_volume_zscore(df, window=20)
        assert result.empty

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = compute_volume_zscore(df, window=20)
        assert result.empty


class TestComputePriceChange:
    def test_returns_correct_columns(self):
        df = make_sample_df(n_days=10)
        result = compute_price_change(df, periods=[1, 3, 5])
        assert "price_change_1d" in result.columns
        assert "price_change_3d" in result.columns
        assert "price_change_5d" in result.columns

    def test_positive_trend(self):
        """Harga naik konsisten → price_change_1d positif."""
        df = make_sample_df(n_days=10)
        result = compute_price_change(df, periods=[1])
        # Semua perubahan harian harus positif (kecuali NaN pertama)
        non_nan = result["price_change_1d"].dropna()
        assert all(non_nan > 0), "Semua price change harus positif untuk trending up"

    def test_missing_close_column(self):
        df = pd.DataFrame({"date": [date.today()], "volume": [1000]})
        result = compute_price_change(df)
        assert result.empty


class TestClassifyVolumePriceScenario:
    def test_normal_low_zscore(self):
        assert classify_volume_price_scenario(0.5, 0.01) == "NORMAL"

    def test_accumulation(self):
        # Volume tinggi, harga flat
        scenario = classify_volume_price_scenario(2.5, -0.005)
        assert scenario == "ACCUMULATION"

    def test_breakout(self):
        # Volume tinggi, harga naik besar
        scenario = classify_volume_price_scenario(3.0, 0.06)
        assert scenario == "BREAKOUT"

    def test_distribution(self):
        # Volume tinggi, harga turun moderat
        scenario = classify_volume_price_scenario(2.5, -0.03)
        assert scenario == "DISTRIBUTION"

    def test_panic(self):
        # Volume ekstrem, harga turun tajam
        scenario = classify_volume_price_scenario(4.0, -0.05)
        assert scenario == "PANIC"


class TestComputeFeaturesForTicker:
    def test_returns_dict_with_required_keys(self):
        df = make_sample_df(n_days=25)
        result = compute_features_for_ticker(df, window=20)
        assert result is not None
        required_keys = {
            "ticker", "date", "close", "volume_today",
            "volume_zscore", "price_change_1d", "scenario"
        }
        assert required_keys.issubset(result.keys())

    def test_insufficient_data_returns_none(self):
        df = make_sample_df(n_days=3)
        result = compute_features_for_ticker(df, window=20)
        assert result is None

    def test_empty_df_returns_none(self):
        result = compute_features_for_ticker(pd.DataFrame(), window=20)
        assert result is None

    def test_spike_detects_high_zscore(self):
        df = make_sample_df(n_days=25, spike_day=24, spike_factor=8.0)
        result = compute_features_for_ticker(df, window=20)
        assert result is not None
        assert result["volume_zscore"] is not None
        assert result["volume_zscore"] > 2.0
