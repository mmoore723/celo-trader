"""Shared quote/bar inputs; execution and research supply separate state."""
import logging

from database import record_underlying_quote
from trading.cross_ticker_shadow import update_orb, update_two_leg
from trading.orb_retouch_execution import update_one_minute_orb_retouch
from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback
from trading.state import _now_et
from trading.diagnostics import orb_evidence

logger = logging.getLogger("celo_trader.trading_logic")
ORB = "V2_ORB_PULLBACK"
TWO_LEG = "V2_TSLA_TWO_LEG_TREND_PULLBACK"


def evaluate_injected_setups(state, frame, ticker, enabled, observed, alpaca, settings, *, research_scope=None):
    if research_scope is not None and (not research_scope.startswith('research_worker:') or enabled):
        raise ValueError('Expanded research cannot run in an order-enabled pass')
    signals, statuses, quote = [], {}, None
    if ORB in enabled | observed:
        try:
            quote = alpaca.get_latest_quote(ticker)
            try:
                record_underlying_quote(
                    ticker, quote, observed_at=_now_et(),
                    broker_account_id=settings.get("active_broker_account_id") or None,
                )
            except Exception:
                logger.debug("underlying quote archive failed", exc_info=True)
            ask, bid = float((quote or {}).get("ap") or 0), float((quote or {}).get("bp") or 0)
            price = (ask + bid) / 2 if ask > 0 and bid > 0 else None
            slot = state.setdefault("v2_orb_retouch", {}).setdefault(ticker.upper(), {})
            evaluate = update_orb if ORB in observed and ticker.upper() != "TSLA" else update_one_minute_orb_retouch
            if research_scope is not None:
                from trading.orb_retouch_research import update
                signal, status = update(state.setdefault('research_orb',{}),frame,
                    ticker=ticker,quote=quote,now=_now_et(),scope=research_scope)
            else:
                decision_now = _now_et()
                evidence = None
                if ORB in enabled and ticker.upper() == 'TSLA':
                    evidence = orb_evidence.begin(slot, frame, now=decision_now,
                        price=price, quote=quote, settings=settings)
                try:
                    signal, status = evaluate(slot, frame, ticker=ticker, quote_price=price, now=decision_now)
                except Exception as exc:
                    orb_evidence.finish(evidence, slot, None, 'evaluation_error', error=type(exc).__name__)
                    raise
                orb_evidence.finish(evidence, slot, signal, status)
            state["v2_orb_retouch_status"] = statuses[ORB] = status
            if signal is not None:
                signals.append(signal)
        except Exception:
            statuses[ORB] = "data_check_failed"
            logger.warning("ORB input evaluation failed for %s", ticker, exc_info=True)
    if TWO_LEG in enabled | observed:
        try:
            slot = state.setdefault("v2_tsla_two_leg_trend_pullback", {}).setdefault(ticker.upper(), {})
            evaluate = update_two_leg if TWO_LEG in observed and ticker.upper() != "TSLA" else update_two_leg_trend_pullback
            if research_scope is not None:
                from trading.two_leg_research import update
                signal, status = update(state.setdefault('research_two_leg',{}),frame,
                    ticker=ticker,now=_now_et(),scope=research_scope)
            else:
                signal, status = evaluate(slot, frame, ticker=ticker, now=_now_et())
            state["v2_tsla_two_leg_trend_pullback_status"] = statuses[TWO_LEG] = status
            if signal is not None:
                signals.append(signal)
        except Exception:
            statuses[TWO_LEG] = "data_check_failed"
            logger.warning("Two-leg input evaluation failed for %s", ticker, exc_info=True)
    return signals, statuses, quote
