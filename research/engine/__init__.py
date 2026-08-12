"""Clean, order-free research foundation for the next trading engine.

Nothing in this package imports the live trading loop or broker order client.
It is safe to run on historical data and produces reproducible research
artifacts only.
"""

from research.engine.models import Bar, Signal, Side, Trade
from research.engine.data import BarDataset, load_csv
from research.engine.simulator import Simulator, SimulationConfig
from research.engine.validation import ValidationConfig, validate
from research.engine.walk_forward import WalkForwardResult, run_walk_forward

__all__ = [
    "Bar", "Signal", "Side", "Trade", "BarDataset", "load_csv", "Simulator", "SimulationConfig",
    "ValidationConfig", "validate",
    "WalkForwardResult", "run_walk_forward",
]
