"""
trading/entry/skip_log.py — Rejection-reason logging for the eval log +
signal journal.

Split out of trading/entry.py (2026-08-01, file-size cleanup); no logic
changed, only relocated.
"""

from __future__ import annotations

import logging

from config import get_bot_state_path
from trading.state import get_user_state, _now_et
from signal_journal import log_signal_outcome as _log_journal

logger = logging.getLogger("celo_trader.trading_logic")


# ── Reject-reason logging helper ─────────────────────────────────────────────

def _skip_log(ticker: str, reason: str, *,
              strategy: str = "", confidence: float = 0.0, rr: float = 0.0,
              direction: str = "", detail: str = "", tier: str = "main") -> None:
    """
    Append a rejection entry to eval_log so the dashboard shows WHY each ticker
    was passed over on a given bar (no signal, low confidence, zero contracts, etc.).

    reason values: "no_signal" | "below_confidence" | "zero_contracts" |
                   "spread_too_wide" | "rr_too_low" | "macro_vwap_veto" |
                   "ai_decision_veto" | "budget" | "illiquid_contract" |
                   "no_option_data" | "no_liquid_contracts"

    2026-07-24: also writes to signal_journal (see signal_journal.py) when a
    real signal was actually rejected (strategy given) — "no_signal" calls
    have no strategy/confidence because there was no signal to journal, only
    an absence of one, so those are skipped here by design, not by accident.

    2026-07-28 FIX: every call site except "rr_too_low" was passing no detail
    at all, so the Thinking panel showed a bare BLOCKED badge with nothing
    explaining why — this is what made an above-floor AI-veto block (77%,
    75%, both > the 74% confidence floor) look unexplained, when the real
    reason (the AI decision-support layer's rationale) was sitting right
    there in the caller and just never got threaded through. `detail` now
    takes priority; `rr` is kept as a fallback for any older call site that
    hasn't been updated to pass detail explicitly.
    """
    if strategy:
        try:
            # tick.py sets this immediately after the router chooses the
            # candidate it is about to evaluate.  Keeping this snapshot with
            # every terminal skip lets Scanner Opportunities join the raw
            # candidate to the exact contract/quantity/exit plan that was
            # considered.  Do not create a context for a bare ``no_signal``
            # log: there was no candidate and therefore nothing to audit.
            _snapshot = get_user_state().get("scanner_opportunity_context") or {}
            _same_candidate = (
                _snapshot.get("ticker") == ticker.upper()
                and _snapshot.get("strategy_id") == strategy
            )
            _context = _snapshot.get("context") if _same_candidate else None
            _log_journal(ticker, strategy, direction or "unknown", confidence,
                         outcome="blocked", reason_code=reason,
                         reason_detail=detail or (f"R:R {rr:.2f}" if rr else ""),
                         context=_context, tier=tier)
        except Exception:
            pass   # journal writes are never allowed to affect entry logic

    _US = get_user_state()
    try:
        _entry: dict = {
            "ts":       _now_et().strftime("%H:%M:%S"),
            "ticker":   ticker,
            "rejected": True,
            "reason":   reason,
        }
        if strategy:    _entry["strategy"]   = strategy
        if confidence:  _entry["confidence"] = round(confidence, 2)
        if rr:          _entry["rr"]         = round(rr, 2)
        _log = list(_US.get("eval_log", []))
        _log.insert(0, _entry)
        # FIX 2026-07-28: cap was 10 across EVERY evaluation on EVERY ticker —
        # with dozens of tickers evaluated multiple times per tick, a single
        # ticker's entry (e.g. a real NFLX entry) could fall off within
        # moments even though it was never removed on purpose. 50 gives real
        # entries room to survive a few minutes of other tickers' activity.
        _US["eval_log"] = _log[:50]
        from config import atomic_update_json
        _sp = get_bot_state_path()
        atomic_update_json(
            _sp, lambda state: {**state, "eval_log": _US["eval_log"]},
        )
    except Exception:
        pass   # non-critical — dashboard still shows whatever was last written
