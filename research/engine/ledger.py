"""Portable immutable trade ledgers for research reproduction and review."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from research.engine.models import Side, Trade


def write_trade_ledger(path: str | Path, trades: Sequence[Trade]) -> None:
    payload = [{
        "strategy_id": trade.strategy_id, "side": trade.side.value,
        "signal_time": trade.signal_time.isoformat(), "entry_time": trade.entry_time.isoformat(),
        "exit_time": trade.exit_time.isoformat(), "entry_price": trade.entry_price,
        "exit_price": trade.exit_price, "quantity": trade.quantity, "gross_pnl": trade.gross_pnl,
        "net_pnl": trade.net_pnl, "mae_pct": trade.mae_pct, "mfe_pct": trade.mfe_pct,
        "exit_reason": trade.exit_reason, "features": dict(trade.features),
    } for trade in trades]
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_trade_ledger(path: str | Path) -> tuple[Trade, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("trade ledger must be a JSON array")
    trades: list[Trade] = []
    for number, row in enumerate(payload, start=1):
        try:
            trades.append(Trade(
                strategy_id=str(row["strategy_id"]), side=Side(row["side"]),
                signal_time=datetime.fromisoformat(row["signal_time"]),
                entry_time=datetime.fromisoformat(row["entry_time"]),
                exit_time=datetime.fromisoformat(row["exit_time"]),
                entry_price=float(row["entry_price"]), exit_price=float(row["exit_price"]),
                quantity=int(row["quantity"]), gross_pnl=float(row["gross_pnl"]), net_pnl=float(row["net_pnl"]),
                mae_pct=float(row["mae_pct"]), mfe_pct=float(row["mfe_pct"]),
                exit_reason=str(row["exit_reason"]), features=dict(row.get("features") or {}),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid trade ledger row {number}: {exc}") from exc
    return tuple(trades)
