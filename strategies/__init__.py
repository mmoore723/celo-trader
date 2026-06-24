"""
strategies/ — individual strategy evaluator modules.

Each module exposes a single public function:
    evaluate(today: pd.DataFrame, ticker: str = "") -> Optional[Signal]

route_signals() in strategy_router.py imports and calls each one.
Shared primitives (Signal, MarketStructureAnalyzer, helpers) live in base.py.
"""
from strategies.base import Signal, MarketStructureAnalyzer  # re-export for convenience
