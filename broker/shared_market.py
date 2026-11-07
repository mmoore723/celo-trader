"""One market-data authority; order/account ownership is unchanged."""
from datetime import datetime, timezone

FEED_POLICY = "tradier_consolidated_v1"


def bar_provenance(rows):
    feeds = {row.get("data_feed", "unknown") for row in rows}
    return {
        "data_feed": next(iter(feeds)) if len(feeds) == 1 else "mixed_or_missing",
        "feed_policy": FEED_POLICY,
        "received_at": max((row.get("received_at", "") for row in rows), default=""),
        "fallback_used": False,
    }


def stamp_bars(rows, base):
    feed = FEED_POLICY if base == "https://api.tradier.com/v1" else "tradier_delayed_or_unknown"
    received = datetime.now(timezone.utc).isoformat()
    return [dict(row, data_feed=feed, received_at=received) for row in rows]


class SharedMarketBroker:
    """Use Tradier for stock data without moving Alpaca orders or accounts.

    No alternate data provider is called on failure. Execution, reconciliation,
    clock/calendar and mandatory order management remain with the selected broker.
    """
    def __init__(self, execution, market):
        self.execution = execution
        self.market = market
        self.feed_policy = FEED_POLICY

    def __getattr__(self, name):
        return getattr(self.execution, name)

    def get_bars(self, symbol, timeframe, limit=100):
        return self.market.get_bars(symbol, timeframe, limit=limit)

    def get_session_bars(self, symbol, timeframe="5Min"):
        return self.market.get_session_bars(symbol, timeframe)

    def get_latest_quote(self, symbol):
        return self.market.get_latest_quote(symbol)

    def get_snapshots(self, symbols):
        return self.market.get_snapshots(symbols)
