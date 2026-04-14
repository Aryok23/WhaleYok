"""
test_scorer.py — Unit tests untuk engine/scorer.py.

Jalankan: pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine.scorer import (
    _compute_volume_score,
    _determine_signal_type,
    score_emiten_v1,
    score_all_emiten,
)


class TestComputeVolumeScore:
    def test_low_zscore_zero_score(self):
        score = _compute_volume_score(0.5, None)
        assert score == 0.0

    def test_zscore_threshold_boundaries(self):
        # zscore = 1.0 → minimal 20
        assert _compute_volume_score(1.0, None) == pytest.approx(20.0, abs=1.0)

        # zscore = 2.0 → sekitar 40
        assert _compute_volume_score(2.0, None) == pytest.approx(40.0, abs=1.0)

        # zscore = 3.0 → sekitar 65
        assert _compute_volume_score(3.0, None) == pytest.approx(65.0, abs=1.0)

        # zscore = 4.0 → sekitar 80
        assert _compute_volume_score(4.0, None) == pytest.approx(80.0, abs=1.0)

    def test_bonus_for_positive_price(self):
        score_no_price = _compute_volume_score(2.5, None)
        score_positive = _compute_volume_score(2.5, 0.01)
        assert score_positive == pytest.approx(score_no_price + 5.0, abs=0.01)

    def test_penalty_for_large_price_drop(self):
        score_no_price = _compute_volume_score(2.5, None)
        score_drop = _compute_volume_score(2.5, -0.03)  # -3%
        assert score_drop == pytest.approx(score_no_price - 10.0, abs=0.01)

    def test_score_capped_at_100(self):
        score = _compute_volume_score(10.0, 0.1)  # extreme z-score + bonus
        assert score <= 100.0

    def test_score_not_negative(self):
        # Penalty -10 pada z-score rendah tidak boleh bikin negatif
        score = _compute_volume_score(1.0, -0.05)
        assert score >= 0.0

    def test_nan_zscore_returns_zero(self):
        import math
        score = _compute_volume_score(float("nan"), None)
        assert score == 0.0

    def test_none_zscore_returns_zero(self):
        score = _compute_volume_score(None, None)
        assert score == 0.0


class TestDetermineSignalType:
    def test_strong_buy(self):
        assert _determine_signal_type(90.0) == "STRONG_BUY"
        assert _determine_signal_type(85.0) == "STRONG_BUY"

    def test_watch_buy(self):
        assert _determine_signal_type(75.0) == "WATCH_BUY"
        assert _determine_signal_type(70.0) == "WATCH_BUY"

    def test_monitor(self):
        assert _determine_signal_type(60.0) == "MONITOR"
        assert _determine_signal_type(50.0) == "MONITOR"

    def test_neutral(self):
        assert _determine_signal_type(40.0) == "NEUTRAL"
        assert _determine_signal_type(30.0) == "NEUTRAL"

    def test_distribusi(self):
        assert _determine_signal_type(20.0) == "DISTRIBUSI"
        assert _determine_signal_type(0.0) == "DISTRIBUSI"


class TestScoreEmitenV1:
    def _make_features(self, zscore=3.0, price_change=0.02, scenario="BREAKOUT"):
        return {
            "ticker": "BBCA",
            "volume_zscore": zscore,
            "price_change_1d": price_change,
            "price_change_3d": 0.05,
            "price_change_5d": 0.08,
            "volume_today": 5_000_000,
            "volume_baseline_20d": 1_000_000,
            "volume_ratio": 5.0,
            "close": 9500.0,
            "scenario": scenario,
        }

    def test_returns_required_keys(self):
        features = self._make_features()
        result = score_emiten_v1(features)
        assert "score" in result
        assert "signal_type" in result
        assert "volume_score" in result
        assert "evidence" in result

    def test_high_zscore_gives_high_score(self):
        features = self._make_features(zscore=4.5, price_change=0.03)
        result = score_emiten_v1(features)
        assert result["score"] >= 70.0, f"Expected score >= 70, got {result['score']}"

    def test_low_zscore_gives_low_score(self):
        features = self._make_features(zscore=0.5, price_change=0.0)
        result = score_emiten_v1(features)
        assert result["score"] == 0.0

    def test_evidence_has_volume_section(self):
        features = self._make_features()
        result = score_emiten_v1(features)
        assert "volume" in result["evidence"]
        assert result["evidence"]["volume"]["zscore"] is not None


class TestScoreAllEmiten:
    def test_sorted_by_score_descending(self):
        features_list = [
            {"ticker": "A", "volume_zscore": 1.5, "price_change_1d": 0.01,
             "volume_today": 1e6, "volume_baseline_20d": 5e5, "volume_ratio": 2.0,
             "close": 1000.0, "price_change_3d": None, "price_change_5d": None,
             "scenario": "NORMAL", "date": None},
            {"ticker": "B", "volume_zscore": 4.0, "price_change_1d": 0.03,
             "volume_today": 5e6, "volume_baseline_20d": 5e5, "volume_ratio": 10.0,
             "close": 5000.0, "price_change_3d": None, "price_change_5d": None,
             "scenario": "BREAKOUT", "date": None},
            {"ticker": "C", "volume_zscore": 2.5, "price_change_1d": -0.01,
             "volume_today": 2e6, "volume_baseline_20d": 5e5, "volume_ratio": 4.0,
             "close": 2000.0, "price_change_3d": None, "price_change_5d": None,
             "scenario": "ACCUMULATION", "date": None},
        ]
        results = score_all_emiten(features_list)
        scores = [r["composite_score"] for r in results]
        assert scores == sorted(scores, reverse=True), "Hasil harus terurut descending"

    def test_none_features_skipped(self):
        features_list = [None, None]
        results = score_all_emiten(features_list)
        assert results == []

    def test_empty_list(self):
        results = score_all_emiten([])
        assert results == []
