"""
broker/factory.py — get_clients(): the one-line factory every caller uses to
build both broker clients together.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from broker.alpaca_client import AlpacaClient
from broker.tradier_client import TradierClient
from broker.tradier_broker import TradierBrokerClient

TRADIER_LIVE_BASE = "https://api.tradier.com/v1"
TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"


def configured_broker_provider() -> str:
    from config import get_settings
    provider = str(get_settings().get("broker_provider") or "alpaca").lower()
    return provider if provider in {"alpaca", "tradier"} else "alpaca"


def required_broker_credentials(
    credentials: dict, *, provider: str | None = None, paper: bool | None = None,
) -> list[tuple[str, str]]:
    settings = None
    if provider is None or paper is None:
        from config import get_settings
        settings = get_settings()
    selected = provider or str((settings or {}).get("broker_provider") or "alpaca").lower()
    is_paper = bool((settings or {}).get("paper_trading", True)) if paper is None else bool(paper)
    if selected == "tradier":
        required = [
            (
                "tradier_api_key" if is_paper else "tradier_market_api_key",
                "Tradier sandbox token" if is_paper else "Tradier live token",
            ),
            (
                "tradier_account_id" if is_paper else "tradier_live_account_id",
                "Tradier sandbox account ID" if is_paper else "Tradier live account ID",
            ),
        ]
        if is_paper:
            required.append(("tradier_market_api_key", "Tradier live market-data token"))
        return required
    return [
        ("alpaca_api_key", "Alpaca API key"),
        ("alpaca_secret_key", "Alpaca secret key"),
        ("tradier_market_api_key", "Tradier live market-data token"),
    ]


def get_tradier_market_client() -> TradierClient:
    """Return the real-time Tradier pricing client when a live token exists.

    Alpaca can remain the temporary paper execution broker, but contract
    selection and order ceilings must not inherit Tradier sandbox's mandatory
    delayed quotes.  Falling back to the legacy configured client keeps the
    existing explicit stale-quote failure when no production token is saved.
    """
    from config import get_api_keys
    keys = get_api_keys()
    market_key = str(keys.get("tradier_market_api_key") or "")
    if not market_key:
        return TradierClient()
    return TradierClient(
        api_key=market_key,
        account_id=str(keys.get("tradier_live_account_id") or ""),
        base_url=TRADIER_LIVE_BASE,
    )


def get_tradier_broker(*, paper: bool | None = None) -> tuple[TradierBrokerClient, TradierClient]:
    from config import get_api_keys, get_settings
    settings = get_settings()
    keys = get_api_keys()
    paper = bool(settings.get("paper_trading", True)) if paper is None else bool(paper)
    execution_key = str(
        keys.get("tradier_api_key" if paper else "tradier_market_api_key") or ""
    )
    execution_account_id = str(
        keys.get("tradier_account_id" if paper else "tradier_live_account_id") or ""
    )
    execution = TradierClient(
        api_key=execution_key,
        account_id=execution_account_id,
        base_url=TRADIER_SANDBOX_BASE if paper else TRADIER_LIVE_BASE,
    )
    market = (
        get_tradier_market_client()
        if paper else
        TradierClient(
            api_key=execution_key,
            account_id=execution_account_id,
            base_url=TRADIER_LIVE_BASE,
        )
    )
    return TradierBrokerClient(execution, market, paper=paper), market


def get_clients() -> tuple[object, TradierClient]:
    if configured_broker_provider() == "tradier":
        return get_tradier_broker()
    return AlpacaClient(), get_tradier_market_client()
