#!/usr/bin/env python3
"""Run a small, explainable dynamic model on a causal intraday feature table.

The model is ridge regression, not a black box.  It learns only from rows
before the declared split, then takes the strongest fixed fraction of
predictions after the split.  The held-out report is an underlying-price
research screen—not an options backtest and never an order command.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


FEATURES = (
    "opening_move_pct", "opening_range_pct", "gap_pct", "gap_aligned",
    "prior_day_return_pct", "prior_day_range_pct", "relative_opening_volume",
)


def _read(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append({
                "timestamp": datetime.fromisoformat(row["timestamp"]), "ticker": row["ticker"],
                "target": float(row["outcome_forward_return_pct"]),
                **{feature: float(row[feature]) for feature in FEATURES},
            })
    if not rows:
        raise ValueError("feature table is empty")
    return sorted(rows, key=lambda row: row["timestamp"])


def _metrics(predictions: np.ndarray, targets: np.ndarray, tickers: list[str], cutoff: float) -> dict:
    selected = np.abs(predictions) >= cutoff
    signed = np.sign(predictions[selected]) * targets[selected]

    def summarize(indices: np.ndarray) -> dict:
        values = signed[indices]
        if len(values) == 0:
            return {"trades": 0, "win_rate_pct": None, "average_return_pct": None}
        return {"trades": int(len(values)), "win_rate_pct": round(float(np.mean(values > 0) * 100), 1),
                "average_return_pct": round(float(np.mean(values)), 4)}

    selected_tickers = np.asarray(tickers)[selected]
    by_ticker = {ticker: summarize(np.where(selected_tickers == ticker)[0]) for ticker in sorted(set(tickers))}
    overall = summarize(np.arange(len(signed)))
    overall["prediction_cutoff_pct"] = round(cutoff, 5)
    overall["per_ticker"] = by_ticker
    return overall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--split", required=True, help="ISO timestamp; later rows are untouched holdout")
    parser.add_argument("--top-fraction", type=float, default=0.20,
                        help="Fixed share of strongest predictions to assess (default: 0.20)")
    parser.add_argument("--ridge", type=float, default=1.0)
    parser.add_argument("--ticker", help="Optional pre-declared single-symbol study, e.g. TSLA")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 0 < args.top_fraction <= 0.5 or args.ridge < 0:
        parser.error("top fraction must be in (0, .5] and ridge must be non-negative")
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    rows = _read(args.csv)
    if args.ticker:
        ticker = args.ticker.upper().strip()
        rows = [row for row in rows if row["ticker"] == ticker]
        if not rows:
            parser.error(f"no rows found for ticker {ticker}")
    train_rows = [row for row in rows if row["timestamp"] < split]
    holdout_rows = [row for row in rows if row["timestamp"] >= split]
    if len(train_rows) < len(FEATURES) * 5 or len(holdout_rows) < 40:
        raise ValueError("need enough chronological train and holdout rows")
    x_train = np.array([[row[feature] for feature in FEATURES] for row in train_rows], dtype=float)
    y_train = np.array([row["target"] for row in train_rows], dtype=float)
    x_holdout = np.array([[row[feature] for feature in FEATURES] for row in holdout_rows], dtype=float)
    y_holdout = np.array([row["target"] for row in holdout_rows], dtype=float)
    means, scales = x_train.mean(axis=0), x_train.std(axis=0)
    scales[scales == 0] = 1.0
    train_design = np.column_stack((np.ones(len(x_train)), (x_train - means) / scales))
    holdout_design = np.column_stack((np.ones(len(x_holdout)), (x_holdout - means) / scales))
    penalty = np.diag([0.0] + [args.ridge] * len(FEATURES))
    coefficients = np.linalg.solve(train_design.T @ train_design + penalty, train_design.T @ y_train)
    train_predictions, holdout_predictions = train_design @ coefficients, holdout_design @ coefficients
    # The entry cutoff is fixed from older data.  Letting the holdout choose
    # its own quantile would quietly use future feature distribution to alter
    # the live decision rate.
    prediction_cutoff = float(np.quantile(np.abs(train_predictions), 1.0 - args.top_fraction))
    payload = {
        "purpose": "Train-only, explainable intraday model; not an options backtest or trading authorization.",
        "design": {
            "model": "standardized ridge regression", "features": list(FEATURES),
            "top_prediction_fraction": args.top_fraction, "ridge": args.ridge,
            "selection": "Only predictions above the absolute cutoff fixed from the training period are evaluated.",
        },
        "split": split.isoformat(), "train_rows": len(train_rows), "holdout_rows": len(holdout_rows),
        "ticker_scope": args.ticker.upper().strip() if args.ticker else "pooled",
        "feature_effects_pct": {feature: round(float(value), 5) for feature, value in zip(FEATURES, coefficients[1:])},
        "train_selected": _metrics(train_predictions, y_train, [str(row["ticker"]) for row in train_rows], prediction_cutoff),
        "holdout_selected": _metrics(holdout_predictions, y_holdout, [str(row["ticker"]) for row in holdout_rows], prediction_cutoff),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
