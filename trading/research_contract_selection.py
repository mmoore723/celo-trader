"""Order-free option-contract policies for prospective strategy research.

This module is deliberately separate from ``trading.entry.contract``.  A
research profile may compare several contracts without changing which
contract an approved strategy is allowed to order.  Nothing in this file has
access to submit, cancel, size, or manage an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from inspect import getattr_static
from typing import Any

from trading.state import _now_et


RESEARCH_CONTRACT_PROFILE_VERSION = "research_contracts_v1"
RESEARCH_CONTRACT_SOURCE = "tradier_research_contract_v1"
RESEARCH_MAX_CONTRACT_DOLLARS = 1_000.0
MAX_SPREAD_PCT = 0.08

_CONTEXT_0_TO_7_DTE = frozenset({
    "CTX_ORB_NR7_OR_INSIDE",
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG",
    "CTX_VWAP_PULLBACK_KER10_LONG",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
})
_TARGET_150_250 = frozenset({
    "CTX_ORB_NR7_OR_INSIDE",
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
})


@dataclass(frozen=True)
class ResearchContractProfile:
    version: str
    minimum_dte: int
    maximum_dte: int
    minimum_premium: float
    maximum_premium: float
    maximum_spread_pct: float
    primary_policy: str
    basis: str


def research_contract_profile(strategy_id: object) -> ResearchContractProfile:
    """Return the declared all-ticker observation profile for one strategy."""
    normalized = str(strategy_id or "").strip().upper()
    if normalized == "CTX_1H_SQUEEZE_MACD_LONG":
        return ResearchContractProfile(
            RESEARCH_CONTRACT_PROFILE_VERSION, 3, 5, 1.50, 10.00,
            MAX_SPREAD_PCT, "closest_otm_150_1000",
            "The paid squeeze specification requires 3–5 DTE options.",
        )
    if normalized in _CONTEXT_0_TO_7_DTE:
        primary = (
            "target_150_250" if normalized in _TARGET_150_250
            else "nearest_weekly_150_1000"
        )
        return ResearchContractProfile(
            RESEARCH_CONTRACT_PROFILE_VERSION, 0, 7, 1.50, 10.00,
            MAX_SPREAD_PCT, primary,
            "The paid context study used same-week OTM options.",
        )
    # Reconstructed underlying-only strategies and cross-ticker extensions of
    # reviewed rules did not prove a universal option profile.  Compare the
    # user-approved $150–$1,000 range prospectively instead of pretending that
    # a historical contract rule exists.
    return ResearchContractProfile(
        RESEARCH_CONTRACT_PROFILE_VERSION, 0, 7, 1.50, 10.00,
        MAX_SPREAD_PCT, "closest_otm_150_1000",
        "Prospective all-ticker comparison in the configured $150–$1,000 range.",
    )


def _spread_pct(contract: dict[str, Any]) -> float:
    ask = float(contract.get("ask") or 0)
    bid = float(contract.get("bid") or 0)
    reported = float(contract.get("spread") or 0)
    spread = max(ask - bid, reported)
    midpoint = (ask + bid) / 2 if ask > 0 and bid > 0 else 0
    return spread / midpoint if midpoint > 0 else float("inf")


def _leaderboard(
    candidates: list[tuple[int, float, float, str, dict[str, Any]]],
    profile: ResearchContractProfile,
) -> tuple[list[dict[str, Any]], str]:
    """Return each concrete policy winner and the selected primary policy."""
    policies: dict[str, tuple[Any, Any]] = {
        "nearest_weekly_150_1000": (
            candidates,
            lambda item: (item[0], item[1], item[2], item[3]),
        ),
        "closest_otm_150_1000": (
            candidates,
            lambda item: (item[1], item[0], item[2], item[3]),
        ),
        "tightest_spread_150_1000": (
            candidates,
            lambda item: (item[2], item[0], item[1], item[3]),
        ),
        "lowest_ask_150_1000": (
            candidates,
            lambda item: (float(item[4].get("ask") or float("inf")), item[0], item[1], item[3]),
        ),
        "highest_open_interest_150_1000": (
            candidates,
            lambda item: (-float(item[4].get("open_interest") or 0), item[2], item[0], item[3]),
        ),
        "highest_volume_150_1000": (
            candidates,
            lambda item: (-float(item[4].get("volume") or 0), item[2], item[0], item[3]),
        ),
    }
    target_candidates = [
        item for item in candidates
        if 1.50 <= float(item[4].get("ask") or 0) <= 2.50
    ]
    if target_candidates:
        policies["target_150_250"] = (
            target_candidates,
            lambda item: (
                abs(float(item[4].get("ask") or 0) - 2.0),
                item[1], item[0], item[2], item[3],
            ),
        )

    selected_policy = profile.primary_policy
    if selected_policy not in policies:
        selected_policy = "closest_otm_150_1000"

    winners: dict[str, dict[str, Any]] = {}
    for policy, (pool, key) in policies.items():
        dte, distance, spread, symbol, contract = min(pool, key=key)
        row = winners.setdefault(symbol, {
            "symbol": symbol,
            "expiry": contract.get("expiry"),
            "dte": int(dte),
            "strike": float(contract.get("strike") or 0),
            "otm_distance": round(float(distance), 4),
            "bid": float(contract.get("bid") or 0),
            "ask": float(contract.get("ask") or 0),
            "spread_pct": round(float(spread), 6),
            "volume": int(float(contract.get("volume") or 0)),
            "open_interest": int(float(contract.get("open_interest") or 0)),
            "policy_winner_for": [],
        })
        row["policy_winner_for"].append(policy)
    return sorted(
        winners.values(),
        key=lambda row: (selected_policy not in row["policy_winner_for"], row["symbol"]),
    ), selected_policy


def select_research_contract(
    tradier: Any, ticker: str, direction: str, current_price: float,
    strategy_id: object,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Read current chains and choose/order-free policy winners up to $1,000."""
    ticker = str(ticker or "").strip().upper()
    direction = str(direction or "").strip().lower()
    profile = research_contract_profile(strategy_id)
    # Workers expose bound reads on a SimpleNamespace instance, not its type.
    # Static lookup also avoids treating auto-created mock/proxy attributes as
    # an explicitly supplied capability.
    research_reader = getattr_static(tradier, "get_research_option_chain", None)
    chain_reader = (tradier.get_research_option_chain if callable(research_reader)
                    else tradier.get_option_chain)
    info: dict[str, Any] = {
        "reason": "no_chain_data",
        "selection_model": profile.version,
        "research_profile": {
            "version": profile.version,
            "min_dte": profile.minimum_dte,
            "max_dte": profile.maximum_dte,
            "min_premium": profile.minimum_premium,
            "max_premium": profile.maximum_premium,
            "max_spread_pct": profile.maximum_spread_pct,
            "primary_policy": profile.primary_policy,
            "maximum_contract_dollars": RESEARCH_MAX_CONTRACT_DOLLARS,
            "basis": profile.basis,
        },
        "upstream_chain_liquidity_filtered": not callable(research_reader),
        "chain_screen": ("research_quote_validity_v1" if callable(research_reader)
                         else "legacy_execution_filters"),
    }
    if direction not in {"bullish", "bearish"} or current_price <= 0:
        info["reason"] = "invalid_selection_input"
        return None, info
    option_type = "call" if direction == "bullish" else "put"
    try:
        expirations = tradier.get_expirations(
            ticker,
            minimum_dte=profile.minimum_dte,
            maximum_dte=profile.maximum_dte,
            limit=8,
        )
    except Exception:
        info["reason"] = "api_error"
        return None, info
    if not expirations:
        info["reason"] = "no_expirations"
        return None, info

    today = _now_et().date()
    candidates: list[tuple[int, float, float, str, dict[str, Any]]] = []
    saw_chain = False
    saw_price = False
    saw_spread = False
    for expiry in expirations:
        try:
            expiry_date = date.fromisoformat(str(expiry))
        except (TypeError, ValueError):
            continue
        dte = (expiry_date - today).days
        if not profile.minimum_dte <= dte <= profile.maximum_dte:
            continue
        try:
            chain = chain_reader(ticker, str(expiry), option_type)
        except Exception:
            continue
        if not chain:
            continue
        saw_chain = True
        for raw in chain:
            contract = dict(raw)
            try:
                strike = float(contract.get("strike") or 0)
                ask = float(contract.get("ask") or 0)
            except (TypeError, ValueError):
                continue
            is_otm = strike > current_price if option_type == "call" else strike < current_price
            if not is_otm or not profile.minimum_premium <= ask <= profile.maximum_premium:
                continue
            saw_price = True
            spread = _spread_pct(contract)
            if spread > profile.maximum_spread_pct:
                saw_spread = True
                continue
            symbol = str(contract.get("symbol") or "")
            if not symbol:
                continue
            contract["expiry"] = str(expiry)
            contract["selection_model"] = profile.version
            candidates.append((dte, abs(strike - current_price), spread, symbol, contract))

    if not candidates:
        info["reason"] = (
            "illiquid" if saw_spread else "filtered" if saw_chain or saw_price
            else "no_chain_data"
        )
        return None, info

    leaderboard, selected_policy = _leaderboard(candidates, profile)
    selected_row = next(
        row for row in leaderboard if selected_policy in row["policy_winner_for"]
    )
    selected = next(item[4] for item in candidates if item[3] == selected_row["symbol"])
    info.update({
        "reason": "selected",
        "selected_policy": selected_policy,
        "primary_policy_available": selected_policy == profile.primary_policy,
        "eligible_contract_count": len(candidates),
        "shadow_contract_leaderboard": leaderboard,
    })
    return selected, info
