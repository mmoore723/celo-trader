"""
broker/tradier_client.py — TradierClient: assembles the three Tradier*Mixin
classes into the concrete client used everywhere else in the app.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. self.X resolves via Python's normal method
resolution order regardless of which mixin file defines X, so every existing
call site (tradier.get_option_chain(...), tradier.place_option_order(...),
etc.) is unaffected.

  tradier_core.py    — TradierCoreMixin  (auth headers, shared GET helper, __init__)
  tradier_chain.py   — TradierChainMixin (option chain, single quote, expirations)
  tradier_orders.py  — TradierOrdersMixin (order submission, earnings lookup)
"""

from broker.tradier_core import TradierCoreMixin
from broker.tradier_chain import TradierChainMixin
from broker.tradier_execution import TradierExecutionMixin
from broker.tradier_market import TradierMarketMixin
from broker.tradier_orders import TradierOrdersMixin


class TradierClient(
    TradierCoreMixin,
    TradierMarketMixin,
    TradierChainMixin,
    TradierExecutionMixin,
    TradierOrdersMixin,
):
    """Tradier REST API — options chain data, single-contract quotes, order routing."""
