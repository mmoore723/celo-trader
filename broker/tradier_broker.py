"""Single-provider Tradier broker boundary with separated market/execution tokens."""
from __future__ import annotations

from typing import Any


class TradierBrokerClient:
    """Route all broker state/orders to Tradier execution and data to Tradier market.

    Paper trading can use a sandbox execution token plus a production market
    token.  This keeps simulated orders in the sandbox without accepting its
    mandatory 15-minute delayed quotes as if they were live signals.
    """

    _MARKET_METHODS = {
        "get_bars", "get_session_bars", "get_latest_quote", "get_snapshots",
        "get_option_quote", "get_option_chain", "get_expirations",
        "get_earnings", "is_market_open",
    }

    def __init__(self, execution: Any, market: Any, *, paper: bool):
        self.execution = execution
        self.market = market
        self.paper = bool(paper)
        self.provider = "tradier"

    def __getattr__(self, name: str):
        owner = self.market if name in self._MARKET_METHODS else self.execution
        return getattr(owner, name)

    @property
    def base(self) -> str:
        return str(self.execution.base)

    @property
    def headers(self) -> dict:
        return self.execution.headers

    @property
    def account_id(self) -> str:
        return str(self.execution.account_id)

    @property
    def api_key(self) -> str:
        return str(self.execution.api_key)

    @property
    def last_rejection_reason(self):
        return getattr(self.execution, "last_rejection_reason", None)

    def readiness(self, *, maximum_quote_age_seconds: float = 120.0) -> dict:
        """Read every load-bearing surface; never submit, alter, or cancel orders."""
        checks: dict[str, dict] = {}

        def check(name: str, operation) -> Any:
            try:
                value = operation()
                checks[name] = {"passed": True, "detail": "available"}
                return value
            except Exception as exc:
                checks[name] = {
                    "passed": False,
                    "detail": f"{type(exc).__name__}: {str(exc)[:180]}",
                }
                return None

        expected_execution = "sandbox.tradier.com" if self.paper else "api.tradier.com"
        checks["execution_environment"] = {
            "passed": expected_execution in self.execution.base,
            "detail": self.execution.base,
        }
        expected_market = "api.tradier.com"
        checks["realtime_market_environment"] = {
            "passed": expected_market in self.market.base,
            "detail": self.market.base,
        }
        account = check("account_balance", self.execution.get_account)
        check("positions", self.execution.get_positions)
        check("orders", self.execution.get_orders)
        check("market_clock", self.market.is_market_open)
        quote = check("market_quote", lambda: self.market.get_latest_quote("SPY"))
        if quote:
            age = quote.get("quote_age_seconds")
            fresh = age is not None and float(age) <= maximum_quote_age_seconds
            checks["market_quote_freshness"] = {
                "passed": fresh,
                "detail": (
                    f"SPY quote age {float(age):.1f}s"
                    if age is not None else "Tradier quote did not include a timestamp"
                ),
            }
            if float(quote.get("bp") or 0) <= 0 or float(quote.get("ap") or 0) <= 0:
                checks["market_quote"]["passed"] = False
                checks["market_quote"]["detail"] = "SPY bid/ask was not positive"
        elif checks["market_quote"]["passed"]:
            checks["market_quote"] = {"passed": False, "detail": "No SPY quote returned"}
        if account and float(account.get("equity") or 0) <= 0:
            checks["account_balance"] = {
                "passed": False, "detail": "Tradier equity was not positive",
            }
        return {
            "provider": "tradier", "paper": self.paper,
            "ready": all(item["passed"] for item in checks.values()),
            "checks": checks,
        }
