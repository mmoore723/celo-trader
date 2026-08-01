"""
api/models/__init__.py — Pydantic response schemas for all FastAPI endpoints.

Split out of the old single api/models.py (2026-08-01, file-size cleanup)
into bot.py, trades.py, market.py, settings.py, analytics.py, news.py,
options.py, backtest.py, reconcile.py, and performance.py; no logic
changed, only relocated. Re-exports every model so every existing
`from api.models import X` call site across the app keeps working
unchanged.
"""

from api.models.bot import BotStatus, BotActionResponse
from api.models.trades import Trade, TradeListResponse
from api.models.market import Bar, Quote, ScannerResult
from api.models.settings import Settings
from api.models.analytics import StrategyRow, HourRow, TickerRow, ExitReasonRow, TradeAnalytics
from api.models.news import NewsArticle
from api.models.options import OptionsChainRow
from api.models.backtest import BacktestRequest, BacktestResult, BacktestJobStatus
from api.models.reconcile import AlpacaOrder, ReconcileRow, ReconcileResponse
from api.models.performance import DailySummary, PerformanceStats

__all__ = [
    "BotStatus", "BotActionResponse",
    "Trade", "TradeListResponse",
    "Bar", "Quote", "ScannerResult",
    "Settings",
    "StrategyRow", "HourRow", "TickerRow", "ExitReasonRow", "TradeAnalytics",
    "NewsArticle",
    "OptionsChainRow",
    "BacktestRequest", "BacktestResult", "BacktestJobStatus",
    "AlpacaOrder", "ReconcileRow", "ReconcileResponse",
    "DailySummary", "PerformanceStats",
]
