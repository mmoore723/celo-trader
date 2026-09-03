"""Read-only credential checks used before saving market-data access."""
from __future__ import annotations

from typing import Any

import requests

from broker.tradier_client import TradierClient

TRADIER_LIVE_BASE = "https://api.tradier.com/v1"


def validate_tradier_market_token(token: str) -> dict[str, Any]:
    """Authenticate a production token with a harmless current-quote request."""
    value = str(token or "").strip()
    if not value:
        return {"ok": False, "code": "missing", "detail": "Enter the Tradier production token."}
    client = TradierClient(api_key=value, account_id="", base_url=TRADIER_LIVE_BASE)
    try:
        payload = client._get("/markets/quotes", {"symbols": "SPY", "greeks": "false"})
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            return {
                "ok": False,
                "code": "unauthorized",
                "detail": (
                    "Tradier rejected this production token. Copy or generate the "
                    "Production Account Access token again; do not use the sandbox token."
                ),
            }
        return {
            "ok": False,
            "code": "http_error",
            "detail": f"Tradier could not verify the production token (HTTP {status or 'error'}).",
        }
    except Exception:
        return {
            "ok": False,
            "code": "unavailable",
            "detail": "Tradier could not be reached to verify the production token. Try again.",
        }

    quote = (payload.get("quotes") or {}).get("quote") if isinstance(payload, dict) else None
    if isinstance(quote, list):
        quote = quote[0] if quote else None
    if not isinstance(quote, dict):
        return {
            "ok": False,
            "code": "no_quote",
            "detail": "Tradier accepted the request but returned no SPY quote. Try again.",
        }
    try:
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        bid = ask = 0.0
    if bid <= 0 or ask <= 0:
        return {
            "ok": False,
            "code": "invalid_quote",
            "detail": "Tradier accepted the token but returned an invalid SPY bid/ask quote.",
        }
    return {"ok": True, "code": "verified", "detail": "Tradier real-time pricing verified."}
