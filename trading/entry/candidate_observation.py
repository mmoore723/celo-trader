"""Read-only contract previews for scanner candidates that cannot trade.

This module intentionally imports contract selectors and database telemetry,
but no broker order, trade insertion, or position-management function.  Its
only purpose is to answer: "which option would the contract screen have shown
when this raw strategy signal appeared, and what happened to that option?"
"""
from __future__ import annotations

import logging
from typing import Any

from config import MIN_CONTRACT_COST, MAX_CONTRACT_COST, MIN_OPEN_INTEREST
from config.strategy_catalog import reviewed_exit_summary
from database.option_quotes import record_candidate_option_quote
from shadow_ledger import record_router_candidate, snapshot_candidate_plan
from trading.entry.contract import select_contract, select_reviewed_v2_contract
from trading.state import _now_et
from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile

logger = logging.getLogger("celo_trader.candidate_observation")


def _max_spend(balance: float, settings: dict) -> float:
    cap_pct = settings.get("max_position_dollars_pct")
    return (
        balance * float(cap_pct) / 100.0
        if cap_pct else float(settings.get("max_position_dollars", 750.0))
    )


def observe_candidate_contract(
    *, ticker: str, signal: object, underlying_price: float | None,
    tradier: Any, balance: float, risk: Any, settings: dict,
    selection_cache: dict[tuple[object, ...], tuple[dict | None, dict]] | None = None,
) -> None:
    """Record a raw candidate and, when possible, its display-only contract."""
    record_router_candidate(ticker, signal, underlying_price)
    meta = getattr(signal, "meta", None)
    candidate_id = meta.get("shadow_candidate_id") if isinstance(meta, dict) else None
    strategy_id = str(getattr(signal, "strategy_id", "UNKNOWN"))
    direction = str(getattr(signal, "direction", "unknown"))
    price = float(underlying_price or 0)
    if not candidate_id or price <= 0:
        return

    reviewed = uses_v2_orb_execution_profile(strategy_id)
    maximum = _max_spend(float(balance), settings)
    cache_key = (
        reviewed, ticker.upper(), direction.lower(), round(price, 4), round(maximum, 2),
    )
    cached = selection_cache.get(cache_key) if selection_cache is not None else None
    if cached is not None:
        cached_contract, cached_info = cached
        contract = dict(cached_contract) if cached_contract else None
        info = dict(cached_info or {})
    else:
        try:
            if reviewed:
                contract, info = select_reviewed_v2_contract(
                    tradier, ticker, direction, price, maximum, for_display=True,
                )
            else:
                contract, info = select_contract(
                    tradier, ticker, direction, price, maximum, for_display=True,
                )
        except Exception:
            contract, info = None, {"reason": "preview_unavailable"}
            logger.debug("candidate contract screen failed for %s", ticker, exc_info=True)
        if selection_cache is not None:
            selection_cache[cache_key] = (
                dict(contract) if contract else None, dict(info or {}),
            )

    preview: dict[str, Any] = {
        "status": "selected" if contract else "not_selected",
        "observed_at": _now_et().isoformat(),
        "underlying_price": round(price, 4),
        "reason": str((info or {}).get("reason") or "not_selected"),
        "cheapest_cost": (info or {}).get("cheapest_cost"),
        "cheapest_symbol": (info or {}).get("cheapest_symbol"),
        "illiquid_cost": (info or {}).get("illiquid_cost"),
        "illiquid_symbol": (info or {}).get("illiquid_symbol"),
        "liquidity_detail": (info or {}).get("illiquid_fail"),
    }
    quantity = None
    if contract:
        ask = float(contract.get("ask") or 0)
        effective_entry = risk.slippage_adjusted_entry(ask)
        quantity = risk.calculate_contracts(effective_entry, balance)
        preview.update({
            "symbol": contract.get("symbol"), "strike": contract.get("strike"),
            "expiry": contract.get("expiry"), "bid": contract.get("bid"),
            "ask": contract.get("ask"), "spread": contract.get("spread"),
            "volume": contract.get("volume"),
            "open_interest": contract.get("open_interest"),
            "selection_model": contract.get("selection_model"),
            "planned_entry_price": round(effective_entry, 4),
            "planned_contracts": int(quantity),
            "estimated_position_cost": round(effective_entry * quantity * 100, 2),
        })
    recipe = {
        "option_type": "CALL" if direction.lower() in {"bullish", "long", "call"} else "PUT",
        "strike_rule": "closest out-of-the-money strike to the underlying at selection",
        "premium_rule": "$0.80–$10.00 ask" if reviewed else f"${MIN_CONTRACT_COST:.2f}–${MAX_CONTRACT_COST:.2f} ask",
        "expiration_rule": "7–21 calendar days to expiration" if reviewed else "first broker-listed expiration with a qualifying contract",
        "spread_rule": "bid/ask spread no wider than 8% of mid",
        "liquidity_rule": "broker-returned liquid chain" if reviewed else f"open interest of at least {MIN_OPEN_INTEREST}",
        "maximum_cost": round(maximum, 2),
        "selection_model": "reviewed paid-quote profile" if reviewed else "standard liquid first-OTM profile",
    }
    context = {
        "strategy_meta": meta,
        "entry_plan": {"trigger": "raw strategy setup detected", "underlying_price": round(price, 4)},
        "contract_recipe": recipe,
        "contract_preview": preview,
        "planned_quantity": int(quantity) if quantity is not None else None,
        "exit_plan": {
            "strategy_id": strategy_id,
            "summary": reviewed_exit_summary(strategy_id, verb="measure"),
        },
    }
    snapshot_candidate_plan(context)
    if contract:
        record_candidate_option_quote(
            candidate_id=candidate_id, contract_symbol=str(contract.get("symbol") or ""),
            observation_kind="entry", observed_at=_now_et(), quote=contract,
            source="tradier_observation_only_preview",
        )
