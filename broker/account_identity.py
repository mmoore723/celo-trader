"""Non-secret broker-account identity used to scope local bot history."""

from __future__ import annotations

import hashlib


def fallback_account_identity(api_key: str, paper_trading: bool) -> str:
    """Return a non-reversible identity when an account lookup is unavailable."""
    digest = hashlib.sha256((api_key or "missing").encode("utf-8")).hexdigest()[:16]
    mode = "paper" if paper_trading else "live"
    return f"alpaca:{mode}:key-{digest}"


def resolve_account_identity(api_key: str, paper_trading: bool, account: dict | None) -> str:
    """Prefer Alpaca's stable account id; never persist the credential itself."""
    account_id = str((account or {}).get("id") or "").strip()
    if not account_id:
        return fallback_account_identity(api_key, paper_trading)
    mode = "paper" if paper_trading else "live"
    return f"alpaca:{mode}:{account_id}"
