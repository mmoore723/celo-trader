"""
tax_engine/sweep.py — Auto-sweep ledger: record_sweep() is called by the
live/paper trading code every time a trade closes in profit, calculating and
persisting the tax reserve amount.

Split out of the old single tax_engine.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

import json
import logging
from datetime import date, datetime

from tax_engine.constants import TAX_SWEEP_PATH
from tax_engine.profile import load_tax_profile, compute_marginal_rate, reserve_for_trade

logger = logging.getLogger("celo_trader.tax_engine")

# ── Sweep ledger ──────────────────────────────────────────────────────────────

def load_sweep_ledger() -> dict:
    """Load the running tax sweep totals."""
    defaults = {
        "total_swept":    0.0,
        "total_profit":   0.0,
        "effective_rate": 0.0,
        "entries":        [],
        "ytd_year":       date.today().year,
    }
    if TAX_SWEEP_PATH.exists():
        try:
            with open(TAX_SWEEP_PATH) as f:
                saved = json.load(f)
            # Reset if new calendar year
            if saved.get("ytd_year") != date.today().year:
                saved["total_swept"]    = 0.0
                saved["total_profit"]   = 0.0
                saved["entries"]        = []
                saved["ytd_year"]       = date.today().year
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def record_sweep(gross_pnl: float, trade_id: int) -> float:
    """
    Called automatically when a profitable trade closes.
    Calculates reserve, logs it to the sweep ledger, returns the reserve amount.
    """
    if gross_pnl <= 0:
        return 0.0

    profile  = load_tax_profile()
    ledger   = load_sweep_ledger()
    tax_info = compute_marginal_rate(
        profile["salary"],
        profile["filing_status"],
        profile["state"],
        ytd_trading_pnl=ledger["total_profit"],
    )

    reserve = reserve_for_trade(gross_pnl, tax_info)

    ledger["total_swept"]    = round(ledger["total_swept"] + reserve, 2)
    ledger["total_profit"]   = round(ledger["total_profit"] + gross_pnl, 2)
    ledger["effective_rate"] = round(
        ledger["total_swept"] / ledger["total_profit"] * 100, 1
    ) if ledger["total_profit"] > 0 else 0.0
    ledger["entries"].append({
        "ts":       datetime.utcnow().isoformat(),
        "trade_id": trade_id,
        "profit":   gross_pnl,
        "reserved": reserve,
        "rate_pct": tax_info["combined_pct"],
    })

    try:
        with open(TAX_SWEEP_PATH, "w") as f:
            json.dump(ledger, f, indent=2)
    except OSError as e:
        logger.error("Failed to write sweep ledger: %s", e)

    logger.info(
        "Tax sweep: trade_id=%d profit=$%.2f reserved=$%.2f (%.1f%%)",
        trade_id, gross_pnl, reserve, tax_info["combined_pct"],
    )
    return reserve


