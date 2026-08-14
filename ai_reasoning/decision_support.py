"""Structured AI opinions for entry-gate calibration.

review_entry() reviews ONE entry the deterministic system (strategy_
router.py's signal, risk.py's R:R gate, the spread/slippage/sizing checks
in trading/entry.py) has ALREADY approved. It may only narrow (reduce
size) or veto that single, already-decided trade — never change
direction, ticker, or contract, and never increase size.

``review_entry`` is synchronous for strategies whose AI policy has separately
passed validation.  Unvalidated strategies call ``observe_entry_async`` so
the model cannot delay or alter their tuned deterministic entry path.

  1. FAILS OPEN. Any error, timeout, or unparseable response returns
     action="approve" — never blocks a trade the deterministic system
     already cleared just because the API had a bad day. Enforced in code
     (_fallback_approve below), not just documented.
  2. size_multiplier is clamped to [0.0, 1.0] in code — the model's text
     can ask for anything; only a value THIS module computes and clamps
     ever reaches the caller.
  3. Every call is logged via database.log_ai_reasoning(event_type=
     'entry_veto'), including failed/timed-out calls — same discipline
     narrator.py already applies.

trading/entry.py is the only caller, gated by two independent config
flags (AI_DECISION_SUPPORT_ENABLED, and AI_DECISION_SUPPORT_ENABLED_LIVE
for live trades specifically) — both False today. This module doesn't
know which mode it's running in; entry.py owns that gate entirely.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from config import AI_DECISION_MODEL, AI_DECISION_TIMEOUT_SEC
from ai_reasoning.client import call_claude
from ai_reasoning.feature_snapshot import build_decision_snapshot

logger = logging.getLogger("celo_trader.ai_reasoning.decision_support")

_MAX_TOKENS = 220  # one validated decision record, never free-form analysis

_SYSTEM_PROMPT = (
    "You are a constrained audit component reviewing ONE options trade entry "
    "for a day-trading bot. You are not a trader, strategist, or creative "
    "assistant. A "
    "deterministic risk/strategy engine has ALREADY approved this trade — "
    "signal fired, confidence cleared the floor, reward-to-risk cleared the "
    "minimum, spread is acceptable, size was already calculated. Your ONLY "
    "role is a final narrow check: APPROVE as-is, REDUCE size (setup looks "
    "weaker than the deterministic checks alone suggest), or VETO entirely "
    "(only for a genuinely bad setup the deterministic checks missed — "
    "conflicting multi-timeframe signals or explicitly measured exhausted "
    "momentum). Use ONLY values present in Trade entry data. Never invent, "
    "estimate, assume, or claim a price, indicator, pattern, news event, or "
    "market condition that is absent. Missing, null, stale, ambiguous, or "
    "conflicting data MUST produce APPROVE because the deterministic engine "
    "remains authoritative. You may NOT suggest a different direction, "
    "ticker, contract, or a size increase — any such suggestion in your "
    "reasoning is ignored by the system. VETO and REDUCE_SIZE require at "
    "least one exact JSON field name in EVIDENCE; the application validates "
    "those fields exist and rejects unsupported opinions. Respond with "
    "EXACTLY one line, this format, no markdown:\n\n"
    "ACTION: <approve|veto|reduce_size> | SIZE: <0 to 1; 1.0 for approve, "
    "e.g. 0.5 to halve size for reduce_size> | EVIDENCE: <comma-separated "
    "exact JSON field names, or none for approve> | REASON: <one factual "
    "sentence under 160 characters>\n\n"
    "Example: ACTION: reduce_size | SIZE: 0.5 | EVIDENCE: trend_1h_bias,"
    "direction | REASON: trend_1h_bias is bearish while direction is bullish."
)


@dataclass
class DecisionResult:
    action:          str            # "approve" | "veto" | "reduce_size"
    size_multiplier: float          # always in [0.0, 1.0] — clamped, never increases size
    rationale:       str
    latency_ms:      Optional[int]
    model:           str
    error:           Optional[str]  # None on a clean parse, else why we fell back to approve


def _fallback_approve(error: str, latency_ms: Optional[int] = None) -> DecisionResult:
    """One path back for anything that isn't a cleanly parsed response — fails open."""
    return DecisionResult(
        action="approve", size_multiplier=1.0, rationale="",
        latency_ms=latency_ms, model=AI_DECISION_MODEL, error=error,
    )


def _parse_response(text: str, snapshot: dict) -> DecisionResult:
    """Fixed-format keyword parse (not JSON — fewer ways to throw on a
    slightly-off response). Any failure raises; review_entry() fails open."""
    parts = {}
    for chunk in text.strip().split("|"):
        if ":" not in chunk:
            continue
        key, _, val = chunk.partition(":")
        parts[key.strip().upper()] = val.strip()

    action = parts.get("ACTION", "").lower()
    if action not in ("approve", "veto", "reduce_size"):
        raise ValueError(f"unrecognized ACTION: {parts.get('ACTION')!r}")

    try:
        size = float(parts.get("SIZE", "1.0"))
    except ValueError:
        raise ValueError(f"unparseable SIZE: {parts.get('SIZE')!r}")

    # Hard clamp — the actual enforcement point for "can never increase
    # size." The model's text is advisory only; this line makes it true.
    size = max(0.0, min(size, 1.0))

    if action == "veto":
        size = 0.0
    elif action == "approve":
        size = 1.0
    elif action == "reduce_size" and size <= 0.0:
        action = "veto"  # a reduce to ~0 is a veto in every way that matters

    rationale = parts.get("REASON", "").strip()[:160]
    if not rationale:
        raise ValueError("missing REASON")

    evidence = [key.strip() for key in parts.get("EVIDENCE", "").split(",") if key.strip()]
    if action in ("veto", "reduce_size"):
        if not evidence:
            raise ValueError("veto/reduce_size requires EVIDENCE")
        missing = [key for key in evidence if key not in snapshot]
        if missing:
            raise ValueError(f"EVIDENCE fields absent from snapshot: {missing}")
        empty = [key for key in evidence if snapshot.get(key) in (None, "", [], {})]
        if empty:
            raise ValueError(f"EVIDENCE fields contain no usable value: {empty}")
    return DecisionResult(
        action=action, size_multiplier=size, rationale=rationale,
        latency_ms=None, model=AI_DECISION_MODEL, error=None,
    )


def review_entry(
    *,
    ticker: str, strategy_id: str, direction: str, confidence: float, rvol: float,
    contract_symbol: str, option_type: str, strike: float, expiry: str,
    n_contracts: int, entry_price: float, rr_ratio: float, paper: bool,
    rsi: Optional[float] = None, macd_hist: Optional[list] = None,
    adx: Optional[float] = None, ema_aligned: Optional[bool] = None,
    trend_1h_bias: Optional[str] = None, trade_id: Optional[int] = None,
    candidate_id: Optional[str] = None,
    enforced: bool = False,
) -> DecisionResult:
    """
    Synchronous review of one already-approved entry. Signature is
    intentionally the ONLY interface: takes the already-decided trade
    params, returns action + size_multiplier, nothing else — no code path
    here can select a different ticker/direction/contract than what the
    caller passed in. Always logs to ai_reasoning_log (imported lazily,
    same import-order reason narrator.py does it).
    """
    from database import log_ai_reasoning

    try:
        snapshot = build_decision_snapshot(
            ticker=ticker, strategy_id=strategy_id, direction=direction,
            confidence=confidence, rvol=rvol, contract_symbol=contract_symbol,
            option_type=option_type, strike=strike, expiry=expiry,
            n_contracts=n_contracts, entry_price=entry_price, rr_ratio=rr_ratio,
            paper=paper, rsi=rsi, macd_hist=macd_hist, adx=adx,
            ema_aligned=ema_aligned, trend_1h_bias=trend_1h_bias, trade_id=trade_id,
            candidate_id=candidate_id,
        )
    except Exception as exc:
        # A bad snapshot fails open exactly like an API error would — this
        # is "this module had a bad day", never "the trade is unsafe."
        logger.warning("review_entry: snapshot build failed (non-fatal): %s", exc)
        result = _fallback_approve(error=f"snapshot_build_failed: {exc}")
        log_ai_reasoning(
            event_type="entry_veto", ticker=ticker, feature_snapshot={},
            prompt="", response_text=None, latency_ms=None,
            model=AI_DECISION_MODEL, error=result.error, trade_id=trade_id,
            applied=False,
        )
        return result

    user_prompt = f"Trade entry data (JSON):\n\n{json.dumps(snapshot, indent=2, default=str)}"
    full_prompt = _SYSTEM_PROMPT + "\n\n" + user_prompt

    call = call_claude(
        system_prompt=_SYSTEM_PROMPT, user_prompt=user_prompt,
        model=AI_DECISION_MODEL, max_tokens=_MAX_TOKENS, timeout_sec=AI_DECISION_TIMEOUT_SEC,
    )

    if call.error or not call.text:
        # Covers every failure call_claude() can report: no API key,
        # timeout, network error, malformed/empty response — it never
        # raises, so this single branch handles all of them.
        result = _fallback_approve(error=call.error or "empty response", latency_ms=call.latency_ms)
    else:
        try:
            result = _parse_response(call.text, snapshot)
            result.latency_ms = call.latency_ms
        except Exception as exc:
            logger.warning("review_entry: response parse failed (non-fatal): %s — text=%r",
                            exc, call.text[:200])
            result = _fallback_approve(error=f"parse_failed: {exc}", latency_ms=call.latency_ms)

    # Keep the exact parsed verdict beside the exact feature inputs.  The
    # calibration scorecard can now compare approves and vetoes without
    # reparsing prose, and candidate_id links either decision to its later
    # executable option quote.
    snapshot["decision_action"] = result.action
    snapshot["decision_size_multiplier"] = result.size_multiplier
    snapshot["decision_error"] = result.error
    snapshot["decision_enforced"] = bool(enforced)

    # ``applied`` must mean the recommendation was authorized to affect the
    # trade, not merely that the model suggested a veto.  Unvalidated
    # strategy opinions are retained as counterfactual calibration evidence.
    applied = bool(enforced) and result.action in ("veto", "reduce_size") and result.error is None

    log_ai_reasoning(
        event_type="entry_veto", ticker=ticker, feature_snapshot=snapshot,
        prompt=full_prompt, response_text=call.text, latency_ms=result.latency_ms,
        model=result.model, error=result.error, trade_id=trade_id, applied=applied,
    )

    return result


def observe_entry_async(*, on_complete=None, **review_kwargs) -> threading.Thread:
    """Record an unvalidated opinion without delaying the entry path."""
    def run() -> None:
        try:
            result = review_entry(enforced=False, **review_kwargs)
        except Exception:
            # review_entry handles expected provider/parse failures itself,
            # but logging/storage failures must also remain detached from the
            # order path.  A None callback result lets the episode retry.
            logger.warning("AI observation worker failed (non-fatal)", exc_info=True)
            result = None
        if on_complete is not None:
            try:
                on_complete(result)
            except Exception:
                logger.debug("AI observation completion callback failed", exc_info=True)

    thread = threading.Thread(target=run, name="ai-entry-observation", daemon=True)
    thread.start()
    return thread
