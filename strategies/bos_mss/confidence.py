"""
strategies/bos_mss/confidence.py — _compute_confidence(): 0-1 confidence
score for a BOS_MSS signal.

Split out of the old single strategies/bos_mss.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""


def _compute_confidence(
    rvol: float,
    rvol_threshold: float,
    atr: float,
    close: float,
    bos_level: float,
    direction: str,
    trend: str,
) -> float:
    """
    0–1 confidence score.
    Components:
      45% — RVOL strength relative to floor (1.5×)
      30% — proximity to BOS level (0 ATRs = full score, 1.5 ATRs = 0)
      25% — trend confirmation
    """
    rvol_score = min((rvol / max(rvol_threshold, 0.01)) / 2.5, 1.0)

    dist_atrs  = abs(close - bos_level) / atr if atr > 0 else 0.0
    prox_score = max(0.0, 1.0 - dist_atrs / 1.5)

    aligned    = (direction == "bullish" and trend == "uptrend") or \
                 (direction == "bearish" and trend == "downtrend")
    trend_score = 1.0 if aligned else (0.6 if trend == "consolidation" else 0.3)

    confidence = 0.45 * rvol_score + 0.30 * prox_score + 0.25 * trend_score
    return round(min(confidence, 1.0), 4)
