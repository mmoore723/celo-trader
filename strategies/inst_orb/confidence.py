"""
strategies/inst_orb/confidence.py — _compute_confidence: the proximity/RVOL/
trend-based confidence scoring formula for a candidate INST_ORB signal.

Split out of the old single strategies/inst_orb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

# ── Confidence scoring ────────────────────────────────────────────────────────

def _compute_confidence(
    rvol: float,
    rvol_threshold: float,
    atr: float,
    close: float,
    or_high: float,
    or_low: float,
    direction: str,
    direction_flipped: bool,
    trend: str,
    is_retest: bool = False,
) -> float:
    """
    0–1 confidence score.

    FIX 2026-07-28 (doc only, no behavior change): this previously described
    5 additive weighted components summing to 100%, including a "10% flip
    quality penalty" line item. That's not what the code does — flip quality
    isn't a separate additive term, it's a multiplicative haircut applied to
    the WHOLE score at the end. Corrected below to match the actual formula.

    Additive components (sum before the flip multiplier):
      35% × rvol_score   — RVOL strength relative to threshold
      25% × prox_score   — proximity to OR boundary (closer = higher, retest
                            entries use a tighter 0–1 ATR scale vs. 0–2 ATR
                            for raw breakouts — though in practice is_retest
                            is always True at the live call site, so the
                            raw-breakout scale is currently unreachable)
      20% × trend_score  — trend alignment (confirmed > consolidation > counter)
      10% flat           — unconditional base component, always added
      10% retest_bonus   — added only when is_retest=True (always True live)
    Then the entire sum is multiplied by flip_multiplier: 0.85× if the
    signal's direction flipped from the original breakout, else 1.0×. This
    haircut applies to every component above, not just its own 10% slice —
    e.g. a flipped signal with a perfect 1.00 pre-multiplier score ends at
    0.85, not 0.90.
    """
    # Score RVOL as excess above threshold, scaled so 2× threshold = full score.
    # Previous /3.0 divisor made rvol_score=0.42 even at 1.5× — too stingy.
    # New formula: threshold = 0, 2× threshold = 1.0. Linear in between.
    rvol_excess = max(rvol - rvol_threshold, 0.0)
    rvol_score  = min(rvol_excess / max(rvol_threshold, 0.01), 1.0)

    boundary   = or_high if direction == "bullish" else or_low
    dist_atrs  = abs(close - boundary) / atr
    # Retest entries should be very close to the boundary (0–0.5 ATR)
    # Raw breakout entries were 0–2 ATR. Tighter scale for retest.
    prox_score = max(0.0, 1.0 - dist_atrs / (1.0 if is_retest else 2.0))

    if direction == "bullish":
        trend_score = 1.0 if trend == "uptrend" else (0.6 if trend == "consolidation" else 0.3)
    else:
        trend_score = 1.0 if trend == "downtrend" else (0.6 if trend == "consolidation" else 0.3)

    flip_multiplier  = 0.85 if direction_flipped else 1.0
    retest_bonus     = 0.10 if is_retest else 0.0

    # FIX 2026-07-31 (profitability audit): weights rebalanced 0.35/0.25 ->
    # 0.45/0.15 (rvol_score / prox_score). This is the module docstring's own
    # deferred finding from 2026-07-21 — losing trades averaged HIGHER
    # confidence (0.85) than winners (0.77) and ~2x the ATR (3.46 vs 1.88).
    # prox_score is ATR-normalized ("close in ATR terms"), so on a choppy,
    # elevated-ATR session it can read as "close to the boundary" even when
    # the underlying move is noisy, not structural. That was left unfixed at
    # n=11 as too thin to safely recalibrate; n is now 19 (still not large,
    # but the direction hasn't reversed) and external research on ORB false
    # breakouts backs the same mechanism — volume/participation confirms a
    # real breakout more reliably than price-distance-in-ATR-terms does,
    # especially in choppy conditions. Dampening the flagged term (prox_score)
    # and shifting weight to the better-evidenced one (rvol_score) is a
    # rebalance of existing components, not a new invented threshold — lower
    # risk than fabricating an ATR% cutoff this bot's own data hasn't tested.
    confidence = (0.45 * rvol_score + 0.15 * prox_score + 0.20 * trend_score + 0.10 + retest_bonus) * flip_multiplier
    return round(min(confidence, 1.0), 4)
