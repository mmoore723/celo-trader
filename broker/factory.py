"""
broker/factory.py — get_clients(): the one-line factory every caller uses to
build both broker clients together.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from broker.alpaca_client import AlpacaClient
from broker.tradier_client import TradierClient


def get_clients() -> tuple[AlpacaClient, TradierClient]:
    return AlpacaClient(), TradierClient()
