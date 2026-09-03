"""Read-only, secret-free status for every broker connection Celo may use."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from broker.credential_validation import validate_tradier_market_token
from broker.factory import TRADIER_SANDBOX_BASE


def _connection(
    connection_id: str,
    label: str,
    purpose: str,
    status: str,
    detail: str,
    *,
    required: bool,
) -> dict[str, Any]:
    return {
        "id": connection_id,
        "label": label,
        "purpose": purpose,
        "status": status,
        "detail": detail,
        "required": required,
    }


def get_connection_health(
    settings: dict[str, Any],
    credentials: dict[str, Any],
    *,
    alpaca_client: Any | None = None,
    tradier_sandbox_client: Any | None = None,
    market_validator: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check active connections without submitting, changing, or canceling orders.

    Complete tokens are used server-side and never included in the result.
    Dependency parameters keep the decision logic deterministic in tests.
    """
    provider = str(settings.get("broker_provider") or "alpaca").lower()
    if provider not in {"alpaca", "tradier"}:
        provider = "alpaca"
    paper = bool(settings.get("paper_trading", True))
    connections: list[dict[str, Any]] = []

    alpaca_required = provider == "alpaca"
    if not alpaca_required:
        connections.append(_connection(
            "alpaca_execution",
            "Alpaca",
            "Order execution",
            "not_used",
            "Not used because Tradier is the selected broker.",
            required=False,
        ))
    else:
        alpaca_key = str(credentials.get("alpaca_api_key") or "").strip()
        alpaca_secret = str(credentials.get("alpaca_secret_key") or "").strip()
        if not alpaca_key or not alpaca_secret:
            connections.append(_connection(
                "alpaca_execution",
                f"Alpaca {'Paper' if paper else 'Live'}",
                "Simulated orders" if paper else "Real-money orders",
                "missing",
                "API key and secret are required.",
                required=True,
            ))
        else:
            try:
                if alpaca_client is None:
                    from broker import AlpacaClient
                    alpaca_client = AlpacaClient(
                        paper=paper,
                        api_key=alpaca_key,
                        secret_key=alpaca_secret,
                    )
                account = alpaca_client.get_account()
                if not isinstance(account, dict) or float(account.get("equity") or 0) <= 0:
                    raise RuntimeError("account returned no positive equity")
                connections.append(_connection(
                    "alpaca_execution",
                    f"Alpaca {'Paper' if paper else 'Live'}",
                    "Simulated orders" if paper else "Real-money orders",
                    "connected",
                    "Authenticated; account and order route are reachable.",
                    required=True,
                ))
            except Exception as exc:
                connections.append(_connection(
                    "alpaca_execution",
                    f"Alpaca {'Paper' if paper else 'Live'}",
                    "Simulated orders" if paper else "Real-money orders",
                    "error",
                    f"Authentication or account check failed ({type(exc).__name__}).",
                    required=True,
                ))

    market_token = str(credentials.get("tradier_market_api_key") or "").strip()
    if not market_token:
        connections.append(_connection(
            "tradier_production_market",
            "Tradier Production",
            "Current option prices",
            "missing",
            "Production Account Access token is required.",
            required=True,
        ))
    else:
        validate = market_validator or validate_tradier_market_token
        validation = validate(market_token)
        connections.append(_connection(
            "tradier_production_market",
            "Tradier Production",
            "Current option prices",
            "connected" if validation.get("ok") else "error",
            (
                "Authenticated; current bid/ask prices are reachable."
                if validation.get("ok") else
                str(validation.get("detail") or "Production token check failed.")
            ),
            required=True,
        ))

    sandbox_required = provider == "tradier" and paper
    if not sandbox_required:
        connections.append(_connection(
            "tradier_sandbox_execution",
            "Tradier Sandbox",
            "Tradier simulated orders",
            "not_used",
            (
                "Not used because simulated orders currently route to Alpaca Paper."
                if provider == "alpaca" else
                "Not used while Tradier is in Live mode."
            ),
            required=False,
        ))
    else:
        sandbox_key = str(credentials.get("tradier_api_key") or "").strip()
        sandbox_account = str(credentials.get("tradier_account_id") or "").strip()
        if not sandbox_key or not sandbox_account:
            connections.append(_connection(
                "tradier_sandbox_execution",
                "Tradier Sandbox",
                "Tradier simulated orders",
                "missing",
                "Sandbox token and account ID are required.",
                required=True,
            ))
        else:
            try:
                if tradier_sandbox_client is None:
                    from broker.tradier_client import TradierClient
                    tradier_sandbox_client = TradierClient(
                        api_key=sandbox_key,
                        account_id=sandbox_account,
                        base_url=TRADIER_SANDBOX_BASE,
                    )
                account = tradier_sandbox_client.get_account()
                if not isinstance(account, dict):
                    raise RuntimeError("account response was unavailable")
                connections.append(_connection(
                    "tradier_sandbox_execution",
                    "Tradier Sandbox",
                    "Tradier simulated orders",
                    "connected",
                    "Authenticated; sandbox account and paper-order route are reachable.",
                    required=True,
                ))
            except Exception as exc:
                connections.append(_connection(
                    "tradier_sandbox_execution",
                    "Tradier Sandbox",
                    "Tradier simulated orders",
                    "error",
                    f"Authentication or account check failed ({type(exc).__name__}).",
                    required=True,
                ))

    ready = all(
        row["status"] == "connected"
        for row in connections
        if row["required"]
    )
    return {
        "ready": ready,
        "selected_broker": provider,
        "mode": "paper" if paper else "live",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "connections": connections,
    }
