"""
router_gates/confluence_mtf.py — Gate 4 (confluence bonus) and Gate 5
(MTF confirmation — soft confidence tax/boost, OFF by default, live-only).

Split out of the old single router_gates.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

from database import log_event as _db_log

logger = logging.getLogger("celo_trader.router_gates")


# ── 4. Confluence bonus ───────────────────────────────────────────────────────
# When 2+ independent strategies agree on direction, this is the highest-
# probability setup. Reward it with a confidence bonus.

def apply_confluence_bonus(signals: list, ticker: str, quiet: bool = False) -> list:
    if not signals:
        return signals
    _top_dir     = signals[0].direction
    _agree_count = sum(1 for _s in signals if _s.direction == _top_dir)
    if _agree_count >= 2:
        _conf_bonus  = min(0.05, (_agree_count - 1) * 0.03)
        _old_top     = signals[0].confidence
        signals[0].confidence = min(0.95, signals[0].confidence + _conf_bonus)
        if not quiet:
            logger.info(
                "router: confluence +%.0f%% for %s %s (%d strategies agree: %.0f%%→%.0f%%)",
                _conf_bonus * 100, ticker, _top_dir, _agree_count,
                _old_top * 100, signals[0].confidence * 100,
            )
            _db_log(
                "INFO", "scan",
                f"{ticker} — Confluence: {_agree_count} strategies agree {_top_dir} "
                f"→ confidence boosted +{_conf_bonus:.0%} to {signals[0].confidence:.0%}",
            )
        signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


# ── 5. MTF confirmation (2026-07-23, professional-strategy-alignment audit) ──
# Gap 3: higher-timeframe (1Hour) agreement is a soft confidence tax/boost —
# NOT a hard block, and OFF by default. This is the one gate in this file
# that can't be backtested the normal way (see trading/mtf_live_gate.py's
# docstring) — it only does anything when the live call site passes a real
# `alpaca` client + per-user `mtf_cache` dict; every other caller (backtester,
# audit tools) leaves both None and this is a complete no-op, unchanged
# behavior. Applies uniformly to every strategy's signals, not just one —
# this is how "align the other strategies with it" was implemented: one
# shared gate in the pipeline instead of duplicating logic per strategy file.

_MTF_BOOST   = 0.05   # 1Hour agrees with the signal's direction
# 2026-07-31: was 0.05. At that size the penalty almost never mattered —
# most signals clear the 0.74 confidence floor with enough room that a
# 5-point ding doesn't change the outcome. Research (Elder's Triple Screen
# and general MTF-confirmation literature) treats higher-timeframe
# disagreement as a real, consequential signal, not a rounding error —
# aligned setups run meaningfully higher win rates than counter-trend ones.
# Raised to 0.12 so a disagreeing 1Hour trend can actually push a borderline
# signal below the floor. Still a SOFT adjustment, never a hard block, per
# CLAUDE.md rule 12 — a strong enough signal can still absorb this and trade.
_MTF_PENALTY = 0.12   # 1Hour disagrees with the signal's direction


def apply_mtf_confirmation(signals: list, ticker: str, alpaca=None, mtf_cache: dict | None = None,
                            quiet: bool = False) -> list:
    if not signals or alpaca is None or mtf_cache is None:
        return signals   # no-op unless the live call site opted in
    from config import get_settings as _gs
    if not bool(_gs().get("mtf_confirmation_enabled", False)):
        return signals

    from trading.mtf_live_gate import get_live_1h_bias
    for sig in signals:
        bias = get_live_1h_bias(alpaca, ticker, sig.direction, mtf_cache)
        if bias == "with":
            sig.confidence = min(0.95, sig.confidence + _MTF_BOOST)
        elif bias == "against":
            sig.confidence = max(0.0, sig.confidence - _MTF_PENALTY)
        # "neutral" (no data / insufficient history) — leave confidence as-is
        if bias != "neutral" and not quiet:
            logger.debug("[%s] %s: 1Hour bias %s (%s)", ticker, sig.strategy_id, bias, sig.direction)
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals
