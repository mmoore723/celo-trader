"""
broker/ — Unified broker interface for Alpaca (equity) and Tradier (options).

Split from the old single broker.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports the exact same public (and the one private-but-
externally-used) names the old flat module did, so every existing
`from broker import X` call site elsewhere in the app is unaffected:

  common.py           — retry/circuit-breaker helpers, audit-log debounce,
                         is_phantom_position_rejection, _extract_partial_fill
  alpaca_core.py       — AlpacaCoreMixin      (HTTP plumbing, account, __init__)
  alpaca_bars.py        — AlpacaBarsMixin      (OHLCV bars/quotes/snapshots)
  alpaca_orders.py      — AlpacaOrdersMixin    (options order submission + fill wait)
  alpaca_positions.py   — AlpacaPositionsMixin (panic close, order cleanup)
  alpaca_client.py       — AlpacaClient (assembles the four mixins above)
  tradier_core.py       — TradierCoreMixin  (auth headers, shared GET helper)
  tradier_chain.py       — TradierChainMixin (option chain, quote, expirations)
  tradier_orders.py      — TradierOrdersMixin (order submission, earnings)
  tradier_client.py       — TradierClient (assembles the three mixins above)
  factory.py              — get_clients()

Fixes applied (audit round 1, from the original flat broker.py):
  C1  - Alpaca option order payload now uses correct v2 options format with legs[]
  S1  - Fill confirmation: poll order status until filled/rejected before returning
  M2  - close_all_positions now wrapped with _retry (3 attempts)
  M2b - Tradier place_option_order also wrapped with retry
  M7  - get_option_quote() added — single-contract price fetch via /markets/quotes
"""

from broker.alpaca_client import AlpacaClient
from broker.tradier_client import TradierClient
from broker.factory import (
    configured_broker_provider, get_clients, get_tradier_broker,
    required_broker_credentials,
)
from broker.tradier_broker import TradierBrokerClient
from broker.common import is_phantom_position_rejection, _cb_is_open, _AlpacaCircuitOpenError

__all__ = [
    "AlpacaClient",
    "TradierClient",
    "TradierBrokerClient",
    "get_clients",
    "get_tradier_broker",
    "configured_broker_provider",
    "required_broker_credentials",
    "is_phantom_position_rejection",
    "_cb_is_open",
    "_AlpacaCircuitOpenError",
]
