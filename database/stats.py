"""
database/stats.py — get_statistics: aggregate account-level stats
(win rate, total P&L, etc.) for the dashboard header.

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from database.connection import get_conn

# ── Aggregate statistics ───────────────────────────────────────────────────────

def get_statistics() -> dict:
    """
    Compute win rate, average win/loss, and max drawdown from closed trades.
    Called by the performance page on each refresh.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT realized_pnl FROM trades WHERE status = 'closed'"
        ).fetchall()

    if not rows:
        return {
            "total_trades": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "max_drawdown": 0.0, "total_pnl": 0.0,
        }

    pnls   = [r["realized_pnl"] for r in rows]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Max drawdown: largest peak-to-trough decline in cumulative equity
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(pnls),
        "win_rate":     len(wins) / len(pnls) if pnls else 0.0,
        "avg_win":      sum(wins)   / len(wins)   if wins   else 0.0,
        "avg_loss":     sum(losses) / len(losses) if losses else 0.0,
        "max_drawdown": max_dd,
        "total_pnl":    sum(pnls),
    }


