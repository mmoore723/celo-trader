"""Non-secret broker-account identity used to scope local bot history."""

from __future__ import annotations

import hashlib


def fallback_account_identity(
    api_key: str, paper_trading: bool, provider: str = "alpaca",
) -> str:
    """Return a non-reversible identity when an account lookup is unavailable."""
    digest = hashlib.sha256((api_key or "missing").encode("utf-8")).hexdigest()[:16]
    mode = "paper" if paper_trading else "live"
    return f"{provider}:{mode}:key-{digest}"


def resolve_account_identity(
    api_key: str, paper_trading: bool, account: dict | None,
    provider: str = "alpaca",
) -> str:
    """Prefer the broker's stable account id; never persist the credential itself."""
    account_id = str((account or {}).get("id") or "").strip()
    if not account_id:
        return fallback_account_identity(api_key, paper_trading, provider)
    mode = "paper" if paper_trading else "live"
    return f"{provider}:{mode}:{account_id}"
