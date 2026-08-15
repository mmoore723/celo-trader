# Celo Trader

Automated options research and paper-trading platform.

## Production strategy catalog

`config/strategy_catalog.py` is the single production allowlist. Only these reviewed strategy IDs may be configured, routed, traded, scored, or taught in the UI:

| Strategy ID | Ticker | Reviewed exit |
|---|---|---|
| `V2_ORB_PULLBACK` | TSLA | 90 minutes |
| `V2_SPY_TREND_CONT` | SPY | 30 minutes |
| `V2_SPY_AFTERNOON_FVG` | SPY | 30 minutes |
| `V2_TSLA_TWO_LEG_TREND_PULLBACK` | TSLA | 90 minutes |

Retired strategy implementations do not remain in production as hidden or disabled code. Existing closed database rows are preserved as historical financial records, but an unknown strategy ID is presented as retired history and cannot enter the router.

## Application responsibilities

- **Scanner Opportunities:** every evaluated current-catalog setup and its path toward a contract or rejection.
- **Trade Journal:** broker-linked entered and closed positions.
- **Strategy Operations:** current deployed paper evidence, decision funnel, gate behavior, and integrity alerts.
- **Simulation Lab:** explicit historical experiments over a selected configuration and date range. It never changes active strategy settings.
- **AI Decision Audit:** Claude input, constrained recommendation, enforcement state, errors, and exact technical replay.
- **Strategy Playbook:** learning material for current-catalog strategies only.

## Core flow

`trading/loop.py` schedules scans. `strategy_router/` evaluates catalog strategies and ranks signals. `trading/entry/` enforces broker, liquidity, affordability, account, and mode safeguards. `trading/position_manager/` manages open positions and exits. `database/` records the complete audit chain. `api/` and `frontend/` expose that evidence.

## Research boundary

Exploratory tuning belongs under `research/` and is excluded from deployment. A research strategy reaches production only after its declared training and untouched later-data checks pass and it is intentionally added to the catalog and full execution path.

## Deployment

Use `./deploy.sh`. Review the staged production diff first; research artifacts and local reports must remain excluded.
