# celo-trader
Automated options day-trading bot

## Codebase map

### Core trading pipeline
Runs on every tick in order:

| File | Role |
|------|------|
| `trading/loop.py` | Main loop, scan scheduling, daily restart |
| `trading/entry.py` | Signal evaluation, option sizing, order execution |
| `trading/position_manager.py` | Stop management, ATR trail, exit logic |
| `trading/state.py` | Shared `LIVE_STATE` dict, Eastern Time clock |
| `trading/controls.py` | Panic close, manual exit |
| `trading/diagnostics.py` | Ghost position detection on startup |

### Strategies
Each file exports an `evaluate(today, ticker)` function that returns a `Signal` or `None`.

| File | Strategy |
|------|----------|
| `strategies/chan_break.py` | Channel trendline rejection / bounce (CHAN_BREAK) |
| `strategies/vwap_pb.py` | VWAP pullback |
| `strategies/bos_mss.py` | Break of structure / market structure shift |
| `strategies/fvg.py` | Fair value gap |
| `strategies/inst_orb.py` | Institutional opening range breakout |
| `strategies/mid_brk.py` | Midday breakout |
| `strategies/trend_cont.py` | Trend continuation |
| `strategies/aft_rev.py` | Afternoon reversal |
| `strategies/base.py` | Shared `Signal` class, `MarketStructureAnalyzer`, RVOL helpers |
| `strategy_router.py` | Runs all strategies, picks highest-confidence signal |

### Supporting logic

| File | Role |
|------|------|
| `risk.py` | Position sizing, daily loss limit, `is_trading_window()` |
| `signals.py` | VWAP bands, bar indicators fed to strategies |
| `scanner.py` | Morning scan that builds the watchlist |
| `broker.py` | Alpaca + Tradier API wrappers |
| `database.py` | SQLite reads/writes, `log_event()` |
| `config.py` | Settings, capital limits, trading windows |

### Web UI
`api/`, `dashboard/`, and `frontend/` — reads bot state, does not affect trade decisions.

## Deployment

Build frontend on Mac (EC2 ARM64 cannot build):
```bash
cd frontend && npm run build
cd .. && git add frontend/dist/ && git commit -m "Rebuild dist" && git push
```

Deploy to EC2:
```bash
cd /opt/celo_trader && git pull && sudo systemctl restart celo-dashboard
```
