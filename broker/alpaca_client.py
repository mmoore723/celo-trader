"""
broker/alpaca_client.py — AlpacaClient: assembles the four Alpaca*Mixin
classes into the concrete client used everywhere else in the app.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. self.X resolves via Python's normal method
resolution order regardless of which mixin file defines X, so every existing
call site (alpaca.get_bars(...), alpaca.place_option_order(...), etc.) is
unaffected.

  alpaca_core.py      — AlpacaCoreMixin      (HTTP plumbing, account, __init__)
  alpaca_bars.py       — AlpacaBarsMixin      (OHLCV bars/quotes/snapshots)
  alpaca_orders.py     — AlpacaOrdersMixin    (options order submission + fill wait)
  alpaca_positions.py  — AlpacaPositionsMixin (panic close, order cleanup)
"""

from broker.alpaca_core import AlpacaCoreMixin
from broker.alpaca_bars import AlpacaBarsMixin
from broker.alpaca_orders import AlpacaOrdersMixin
from broker.alpaca_positions import AlpacaPositionsMixin


class AlpacaClient(AlpacaCoreMixin, AlpacaBarsMixin, AlpacaOrdersMixin, AlpacaPositionsMixin):
    """Alpaca REST API v2 — equity bars, account data, paper/live options orders."""
    durable_order_recovery = True
