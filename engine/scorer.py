"""
scorer.py — Composite signal scoring engine.

Fase 1: hanya menggunakan volume score (weight 100%).
Fase 2+: akan ditambah broker_score dan foreign_score.

Score range: 0-100.
Signal types berdasarkan score:
  >=85: STRONG_BUY
  70-84: WATCH_BUY
  50-69: MONITOR
  30-49: NEUTRAL
  <30: DISTRIBUSI (hanya jika sebelumnya tinggi)
"""

import logging
import math

logger = logging.getLogger(__name__)

# Bobot per fase (Fase 1: volume 100%)
WEIGHTS_FASE_1 = {
    "volume": 1.0,
}

# Threshold signal type
SIGNAL_THRESHOLDS = {
    "STRONG_BUY": 85.0,
    "WATCH_BUY": 70.0,
    "MONITOR": 50.0,
    "NEUTRAL": 30.0,
    # Di bawah 30: DISTRIBUSI
}


def _compute_volume_score(volume_zscore: float, price_change_1d: float | None) -> float:
    """Hitung volume score berdasarkan z-score dan price action.

    Logika scoring:
    - zscore < 1: score = 0
    - zscore 1-2: score = 20-40 (linear interpolasi)
    - zscore 2-3: score = 40-65 (linear interpolasi)
    - zscore 3-4: score = 65-80 (linear interpolasi)
    - zscore > 4: score = 80-95

    Modifier:
    - Bonus +5 jika harga naik hari ini (price_change_1d > 0)
    - Penalty -10 jika volume naik tapi harga turun > 2%

    Args:
        volume_zscore: Z-score volume hari ini
        price_change_1d: Perubahan harga hari ini (fraksi, misal 0.03 = +3%)

    Returns:
        Score float dalam range 0-100.
    """
    if volume_zscore is None or math.isnan(volume_zscore):
        return 0.0

    # Base score berdasarkan z-score
    if volume_zscore < 1.0:
        base_score = 0.0
    elif volume_zscore < 2.0:
        # Linear: 1.0 → 20, 2.0 → 40
        base_score = 20.0 + (volume_zscore - 1.0) * 20.0
    elif volume_zscore < 3.0:
        # Linear: 2.0 → 40, 3.0 → 65
        base_score = 40.0 + (volume_zscore - 2.0) * 25.0
    elif volume_zscore < 4.0:
        # Linear: 3.0 → 65, 4.0 → 80
        base_score = 65.0 + (volume_zscore - 3.0) * 15.0
    else:
        # 4.0+: cap di 95 secara linear sampai zscore=6
        extra = min(volume_zscore - 4.0, 2.0)
        base_score = 80.0 + extra * 7.5  # 80 → 95

    # Modifier harga
    modifier = 0.0
    if price_change_1d is not None and not math.isnan(price_change_1d):
        if price_change_1d > 0:
            modifier += 5.0
        elif price_change_1d < -0.02:
            modifier -= 10.0

    score = max(0.0, min(100.0, base_score + modifier))
    return round(score, 2)


def _determine_signal_type(score: float) -> str:
    """Tentukan signal type berdasarkan composite score.

    Args:
        score: Composite score 0-100.

    Returns:
        Signal type string.
    """
    if score >= SIGNAL_THRESHOLDS["STRONG_BUY"]:
        return "STRONG_BUY"
    elif score >= SIGNAL_THRESHOLDS["WATCH_BUY"]:
        return "WATCH_BUY"
    elif score >= SIGNAL_THRESHOLDS["MONITOR"]:
        return "MONITOR"
    elif score >= SIGNAL_THRESHOLDS["NEUTRAL"]:
        return "NEUTRAL"
    else:
        return "DISTRIBUSI"


def score_emiten_v1(features: dict) -> dict:
    """Hitung composite score untuk satu emiten (Fase 1: volume only).

    Args:
        features: Dict dari engine/features.py compute_features_for_ticker().
                  Keys yang digunakan:
                    - volume_zscore: float | None
                    - price_change_1d: float | None
                    - scenario: str

    Returns:
        Dict dengan keys:
          - score: float (0-100)
          - signal_type: str
          - volume_score: float
          - evidence: dict (detail untuk Telegram & database)
    """
    volume_zscore = features.get("volume_zscore")
    price_change_1d = features.get("price_change_1d")
    scenario = features.get("scenario", "NORMAL")

    volume_score = _compute_volume_score(volume_zscore, price_change_1d)

    # Fase 1: composite = volume saja (weight 100%)
    composite_score = volume_score * WEIGHTS_FASE_1["volume"]
    composite_score = round(composite_score, 2)

    signal_type = _determine_signal_type(composite_score)

    evidence = {
        "volume": {
            "today": features.get("volume_today"),
            "baseline_20d": features.get("volume_baseline_20d"),
            "ratio": features.get("volume_ratio"),
            "zscore": volume_zscore,
        },
        "price": {
            "close": features.get("close"),
            "change_1d": price_change_1d,
            "change_3d": features.get("price_change_3d"),
            "change_5d": features.get("price_change_5d"),
        },
        "scenario": scenario,
    }

    return {
        "score": composite_score,
        "signal_type": signal_type,
        "volume_score": volume_score,
        "evidence": evidence,
    }


def score_all_emiten(features_list: list[dict]) -> list[dict]:
    """Score semua emiten dan return list sinyal terurut dari score tertinggi.

    Args:
        features_list: List dict dari compute_features_for_ticker() untuk semua emiten.

    Returns:
        List dict sinyal, diurutkan dari composite_score tertinggi ke terendah.
        Setiap dict berisi: ticker, date, composite_score, signal_type,
        volume_zscore, volume_score, evidence_json, phase
    """
    results = []

    for features in features_list:
        if features is None:
            continue

        ticker = features.get("ticker", "")
        target_date = features.get("date")

        try:
            scored = score_emiten_v1(features)
        except Exception as exc:
            logger.warning(f"score_all_emiten: gagal score {ticker}: {exc}")
            continue

        results.append({
            "ticker": ticker,
            "date": target_date,
            "composite_score": scored["score"],
            "signal_type": scored["signal_type"],
            "phase": features.get("scenario", "NORMAL"),
            "volume_zscore": features.get("volume_zscore"),
            "volume_score": scored["volume_score"],
            "broker_score": None,   # fase 2
            "foreign_score": None,  # fase 2
            "news_score": None,     # fase 3
            "evidence_json": scored["evidence"],
            "sent_to_telegram": False,
        })

    # Sort by composite_score descending
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return results
