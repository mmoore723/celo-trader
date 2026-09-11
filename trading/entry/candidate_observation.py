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
from database.option_quotes import record_candidate_contract_alternative, record_candidate_option_quote
from shadow_ledger import record_router_candidate, snapshot_candidate_plan
from trading.entry.contract import (
    reviewed_contract_profile, select_contract, select_reviewed_v2_contract,
)
from trading.research_contract_selection import (
    RESEARCH_CONTRACT_SOURCE, RESEARCH_MAX_CONTRACT_DOLLARS, research_contract_profile,
    select_research_contract,
)
from trading.state import _now_et
from trading.v2_orb_paper_execution import entry_limit_prices
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
    research_only: bool = False,
) -> None:
    """Record a raw candidate and, when possible, its display-only contract."""
    if research_only and isinstance(getattr(signal, 'meta', None), dict):
        from strategy_health.context_orb_exit import metadata
        from strategy_health.context_vwap_exit import metadata as vwap_metadata
        from strategy_health.squeeze_exit import metadata as squeeze_metadata
        from strategy_health.option_profit_protection import metadata as profit_metadata
        from strategy_health.initial_loss_protection import metadata as loss_metadata
        signal.meta.update(loss_metadata(str(getattr(signal, 'strategy_id', ''))))
        signal.meta.update(profit_metadata(str(getattr(signal, 'strategy_id', ''))))
        signal.meta.update(metadata(str(getattr(signal, 'strategy_id', ''))))
        signal.meta.update(vwap_metadata(str(getattr(signal, 'strategy_id', ''))))
        signal.meta.update(squeeze_metadata(str(getattr(signal, 'strategy_id', ''))))
    record_router_candidate(ticker, signal, underlying_price)
    meta = getattr(signal, "meta", None)
    if isinstance(meta,dict) and meta.get('research_existing_candidate'):
        return  # Preserve the original entry/contract; never reprice a replay.
    candidate_id = meta.get("shadow_candidate_id") if isinstance(meta, dict) else None
    strategy_id = str(getattr(signal, "strategy_id", "UNKNOWN"))
    direction = str(getattr(signal, "direction", "unknown"))
    price = float(underlying_price or 0)
    if not candidate_id or price <= 0:
        return

    if research_only:
        from trading.entry.reference_contract_observation import observe as observe_reference
        try:
            observe_reference(candidate_id=candidate_id, strategy_id=strategy_id, ticker=ticker,
                              direction=direction, price=price, meta=meta, tradier=tradier,
                              selection_cache=selection_cache)
        except Exception:
            logger.warning('Reference contract observation failed for %s; main research continues', ticker, exc_info=True)

    reviewed = uses_v2_orb_execution_profile(strategy_id)
    research_profile = research_contract_profile(strategy_id) if research_only else None
    maximum = (
        RESEARCH_MAX_CONTRACT_DOLLARS
        if research_only else _max_spend(float(balance), settings)
    )
    cache_key = (
        "research" if research_only else "execution_preview",
        strategy_id.upper(),
        research_profile.version if research_profile else None,
        reviewed, ticker.upper(), direction.lower(), round(price, 4), round(maximum, 2),
    )
    cached = selection_cache.get(cache_key) if selection_cache is not None else None
    if cached is not None:
        cached_contract, cached_info = cached
        contract = dict(cached_contract) if cached_contract else None
        info = dict(cached_info or {})
    else:
        try:
            if research_only:
                contract, info = select_research_contract(
                    tradier, ticker, direction, price, strategy_id,
                )
            elif reviewed:
                contract, info = select_reviewed_v2_contract(
                    tradier, ticker, direction, price, maximum, for_display=True,
                    strategy_id=strategy_id,
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
        "eligible_contract_count": (info or {}).get("eligible_contract_count"),
        "shadow_contract_leaderboard": (info or {}).get("shadow_contract_leaderboard", []),
        "research_profile": (info or {}).get("research_profile"),
        "chain_screen": (info or {}).get("chain_screen"),
        "upstream_chain_liquidity_filtered": (info or {}).get("upstream_chain_liquidity_filtered"),
        "selected_policy": (info or {}).get("selected_policy"),
    }
    quantity = None
    if contract:
        bid = float(contract.get("bid") or 0)
        ask = float(contract.get("ask") or 0)
        midpoint = round((bid + ask) / 2.0, 4) if bid > 0 else ask
        working_limit, step_limit = entry_limit_prices(
            ask=ask, midpoint=midpoint,
            v2_paper_pilot=reviewed or research_only,
        )
        maximum_entry = ask if research_only else risk.slippage_adjusted_entry(ask)
        # Quantity remains sized at the hard ceiling, not at the optimistic
        # first limit. That prevents a reprice from exceeding approved risk.
        quantity = 1 if research_only else risk.calculate_contracts(maximum_entry, balance)
        preview.update({
            "symbol": contract.get("symbol"), "strike": contract.get("strike"),
            "expiry": contract.get("expiry"), "bid": contract.get("bid"),
            "ask": contract.get("ask"), "spread": contract.get("spread"),
            "volume": contract.get("volume"),
            "open_interest": contract.get("open_interest"),
            "selection_model": contract.get("selection_model"),
            # Backward-compatible field: this is now the price the order would
            # actually try first, rather than the risk-only slippage ceiling.
            "planned_entry_price": round(working_limit, 4),
            "working_limit": round(working_limit, 4),
            "step_limit": round(step_limit, 4) if step_limit is not None else None,
            "maximum_entry_price": round(maximum_entry, 4),
            "planned_contracts": int(quantity),
            "estimated_position_cost": round(maximum_entry * quantity * 100, 2),
        })
    reviewed_profile = (
        reviewed_contract_profile(strategy_id, ticker)
        if reviewed and not research_only else None
    )
    recipe = {
        "option_type": "CALL" if direction.lower() in {"bullish", "long", "call"} else "PUT",
        "strike_rule": (
            "compare declared out-of-the-money contract policies"
            if research_only else
            "closest out-of-the-money strike to the underlying at selection"
        ),
        "premium_rule": (
            f"${research_profile.minimum_premium:.2f}–${research_profile.maximum_premium:.2f} ask"
            if research_profile else
            f"${reviewed_profile.minimum_premium:.2f}–${reviewed_profile.maximum_premium:.2f} ask"
            if reviewed_profile else f"${MIN_CONTRACT_COST:.2f}–${MAX_CONTRACT_COST:.2f} ask"
        ),
        "expiration_rule": (
            f"{research_profile.minimum_dte}–{research_profile.maximum_dte} calendar days to expiration"
            if research_profile else
            f"{reviewed_profile.minimum_dte}–{reviewed_profile.maximum_dte} calendar days to expiration"
            if reviewed_profile else "first broker-listed expiration with a qualifying contract"
        ),
        "spread_rule": "bid/ask spread no wider than 8% of mid",
        "liquidity_rule": (
            "broker-returned liquid chain"
            if research_only or reviewed else
            f"open interest of at least {MIN_OPEN_INTEREST}"
        ),
        "maximum_cost": round(maximum, 2),
        "selection_model": (
            research_profile.version if research_profile else
            reviewed_profile.selection_model if reviewed_profile else "standard liquid first-OTM profile"
        ),
        "purpose": "research_only_no_orders" if research_only else "execution_preview",
        "research_profile": (info or {}).get("research_profile") if research_only else None,
        "selected_policy": (info or {}).get("selected_policy") if research_only else None,
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
            source=(
                RESEARCH_CONTRACT_SOURCE
                if research_only else "tradier_observation_only_preview"
            ),
        )
    for alternative in preview.get("shadow_contract_leaderboard", []):
        record_candidate_contract_alternative(
            candidate_id=candidate_id, contract=alternative,
            observation_kind="entry", observed_at=_now_et(),
            policies=alternative.get("policy_winner_for", []),
            source=(
                RESEARCH_CONTRACT_SOURCE
                if research_only else "reviewed_selector_shadow"
            ),
        )
