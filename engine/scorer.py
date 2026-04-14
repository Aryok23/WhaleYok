"""
scorer.py — Composite signal scoring engine.

Fase 1: volume 100%
Fase 2: volume 40% + broker 40% + foreign 20%

Score range: 0-100 per faktor, lalu digabung berdasarkan bobot.
Signal types berdasarkan composite score:
  >=85: STRONG_BUY
  70-84: WATCH_BUY
  50-69: MONITOR
  30-49: NEUTRAL
  <30: DISTRIBUSI
"""

import logging
import math

logger = logging.getLogger(__name__)

# Bobot per fase
WEIGHTS_FASE_1 = {"volume": 1.0, "broker": 0.0, "foreign": 0.0}
WEIGHTS_FASE_2 = {"volume": 0.4, "broker": 0.4, "foreign": 0.2}

# Threshold signal type
SIGNAL_THRESHOLDS = {
    "STRONG_BUY": 85.0,
    "WATCH_BUY": 70.0,
    "MONITOR": 50.0,
    "NEUTRAL": 30.0,
}


def _compute_volume_score(volume_zscore: float, price_change_1d: float | None) -> float:
    """Hitung volume score berdasarkan z-score dan price action.

    Logika:
    - zscore < 1: score 0
    - zscore 1-2: score 20-40
    - zscore 2-3: score 40-65
    - zscore 3-4: score 65-80
    - zscore > 4: score 80-95
    Modifier: +5 harga naik, -10 harga turun >2%

    Args:
        volume_zscore: Z-score volume hari ini
        price_change_1d: Perubahan harga hari ini (fraksi)

    Returns:
        Score float 0-100.
    """
    if volume_zscore is None or math.isnan(volume_zscore):
        return 0.0

    if volume_zscore < 1.0:
        base_score = 0.0
    elif volume_zscore < 2.0:
        base_score = 20.0 + (volume_zscore - 1.0) * 20.0
    elif volume_zscore < 3.0:
        base_score = 40.0 + (volume_zscore - 2.0) * 25.0
    elif volume_zscore < 4.0:
        base_score = 65.0 + (volume_zscore - 3.0) * 15.0
    else:
        extra = min(volume_zscore - 4.0, 2.0)
        base_score = 80.0 + extra * 7.5

    modifier = 0.0
    if price_change_1d is not None and not math.isnan(price_change_1d):
        if price_change_1d > 0:
            modifier += 5.0
        elif price_change_1d < -0.02:
            modifier -= 10.0

    return round(max(0.0, min(100.0, base_score + modifier)), 2)


def _compute_broker_score(broker_data: dict | None) -> float:
    """Hitung broker score dari data net value per kategori.

    Logika:
    - Asing net buy besar → score tinggi (sinyal paling kuat)
    - Institusi net buy → score medium-tinggi
    - Retail dominan (asing/institusi jual) → score rendah

    Args:
        broker_data: Output dari compute_broker_net_by_category().
                     Keys: asing_net, institusi_net, retail_net, smart_money_net

    Returns:
        Score float 0-100.
    """
    if not broker_data:
        return 50.0  # netral jika tidak ada data

    asing_net = broker_data.get("asing_net", 0.0)
    institusi_net = broker_data.get("institusi_net", 0.0)
    smart_money_net = broker_data.get("smart_money_net", 0.0)
    retail_net = broker_data.get("retail_net", 0.0)

    # Normalisasi berdasarkan total turnover (pakai smart_money + retail sebagai proxy)
    total_abs = abs(smart_money_net) + abs(retail_net)
    if total_abs == 0:
        return 50.0

    # Rasio smart money terhadap total aktivitas (-1 hingga +1)
    smart_ratio = smart_money_net / total_abs

    # Konversi ke skor 0-100
    # smart_ratio = +1.0 → score 100
    # smart_ratio =  0.0 → score 50
    # smart_ratio = -1.0 → score 0
    base_score = 50.0 + smart_ratio * 50.0

    # Bonus jika asing adalah motor utamanya
    asing_bonus = 0.0
    if asing_net > 0 and asing_net >= institusi_net:
        asing_bonus = 10.0

    return round(max(0.0, min(100.0, base_score + asing_bonus)), 2)


def _compute_foreign_score(foreign_data: dict | None) -> float:
    """Hitung foreign score dari net flow dan tren.

    Logika:
    - Foreign net buy hari ini + tren akumulasi → score tinggi
    - Foreign net sell → score rendah
    - Konsistensi (berturut-turut) → bonus

    Args:
        foreign_data: Dict dengan keys:
                      foreign_net, foreign_net_5d, consecutive_buy, trend

    Returns:
        Score float 0-100.
    """
    if not foreign_data:
        return 50.0  # netral jika tidak ada data

    foreign_net = foreign_data.get("foreign_net", 0.0)
    net_5d = foreign_data.get("foreign_net_5d", 0.0)
    consecutive = foreign_data.get("consecutive_buy", 0)
    trend = foreign_data.get("trend", "NETRAL")

    # Base score dari net hari ini
    if foreign_net > 0:
        base_score = 60.0
    elif foreign_net < 0:
        base_score = 30.0
    else:
        base_score = 50.0

    # Modifier dari tren 5 hari
    trend_modifier = 0.0
    if net_5d > 0:
        trend_modifier = min(15.0, net_5d / 1e9 * 5)  # max +15 untuk setiap 1M net
    elif net_5d < 0:
        trend_modifier = max(-15.0, net_5d / 1e9 * 5)

    # Bonus konsistensi akumulasi
    consistency_bonus = 0.0
    if consecutive >= 5:
        consistency_bonus = 15.0
    elif consecutive >= 3:
        consistency_bonus = 8.0
    elif consecutive >= 2:
        consistency_bonus = 4.0

    # Penalty jika trend distribusi
    if trend == "DISTRIBUSI":
        trend_modifier -= 10.0

    score = base_score + trend_modifier + consistency_bonus
    return round(max(0.0, min(100.0, score)), 2)


def _determine_signal_type(score: float) -> str:
    """Tentukan signal type berdasarkan composite score."""
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


def _detect_conflict(volume_score: float, broker_score: float, foreign_score: float) -> str | None:
    """Deteksi konflik antar sinyal faktor.

    Konflik = volume/broker tinggi tapi asing justru jual, atau sebaliknya.

    Returns:
        String deskripsi konflik, atau None jika tidak ada konflik.
    """
    scores_available = [s for s in [broker_score, foreign_score] if s != 50.0]
    if not scores_available:
        return None

    high = [s for s in [volume_score, broker_score, foreign_score] if s >= 65]
    low = [s for s in [volume_score, broker_score, foreign_score] if s <= 35]

    if high and low:
        return "KONFLIK_SINYAL"
    return None


def score_emiten(
    features: dict,
    broker_data: dict | None = None,
    foreign_data: dict | None = None,
    fase: int = 2,
) -> dict:
    """Hitung composite score untuk satu emiten.

    Args:
        features: Dict dari compute_features_for_ticker().
        broker_data: Output dari compute_broker_net_by_category(). None = skip.
        foreign_data: Dict foreign flow + tren. None = skip.
        fase: 1 = volume only, 2 = volume+broker+foreign

    Returns:
        Dict dengan keys:
          - score: float composite (0-100)
          - signal_type: str
          - volume_score: float
          - broker_score: float (None jika fase 1)
          - foreign_score: float (None jika fase 1)
          - conflict: str | None
          - evidence: dict
    """
    volume_zscore = features.get("volume_zscore")
    price_change_1d = features.get("price_change_1d")

    volume_score = _compute_volume_score(volume_zscore, price_change_1d)

    if fase == 1 or (broker_data is None and foreign_data is None):
        weights = WEIGHTS_FASE_1
        broker_score_val = None
        foreign_score_val = None
        composite = volume_score
    else:
        weights = WEIGHTS_FASE_2
        broker_score_val = _compute_broker_score(broker_data)
        foreign_score_val = _compute_foreign_score(foreign_data)
        composite = (
            volume_score * weights["volume"]
            + broker_score_val * weights["broker"]
            + foreign_score_val * weights["foreign"]
        )

    composite = round(composite, 2)
    signal_type = _determine_signal_type(composite)

    conflict = None
    if broker_score_val is not None and foreign_score_val is not None:
        conflict = _detect_conflict(volume_score, broker_score_val, foreign_score_val)

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
        "broker": broker_data or {},
        "foreign": foreign_data or {},
        "scenario": features.get("scenario", "NORMAL"),
        "conflict": conflict,
    }

    return {
        "score": composite,
        "signal_type": signal_type,
        "volume_score": volume_score,
        "broker_score": broker_score_val,
        "foreign_score": foreign_score_val,
        "conflict": conflict,
        "evidence": evidence,
    }


# Alias untuk backward compatibility Fase 1
def score_emiten_v1(features: dict) -> dict:
    return score_emiten(features, fase=1)


def score_all_emiten(
    features_list: list[dict],
    broker_map: dict[str, dict] | None = None,
    foreign_map: dict[str, dict] | None = None,
    fase: int = 2,
) -> list[dict]:
    """Score semua emiten dan return list sinyal terurut dari score tertinggi.

    Args:
        features_list: List dict dari compute_features_for_ticker().
        broker_map: Dict {ticker: broker_data}. None = tidak pakai broker score.
        foreign_map: Dict {ticker: foreign_data}. None = tidak pakai foreign score.
        fase: 1 atau 2.

    Returns:
        List dict sinyal diurutkan composite_score tertinggi ke terendah.
    """
    results = []

    for features in features_list:
        if features is None:
            continue

        ticker = features.get("ticker", "")
        target_date = features.get("date")

        broker_data = (broker_map or {}).get(ticker)
        foreign_data = (foreign_map or {}).get(ticker)

        try:
            scored = score_emiten(features, broker_data, foreign_data, fase=fase)
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
            "broker_score": scored["broker_score"],
            "foreign_score": scored["foreign_score"],
            "news_score": None,  # fase 3
            "conflict": scored["conflict"],
            "evidence_json": scored["evidence"],
            "sent_to_telegram": False,
        })

    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return results
