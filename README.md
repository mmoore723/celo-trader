# Celo Trader

Options trading, forward research, and strategy education in one application.
The backend is Python/FastAPI; the interface is React/TypeScript with Vite.
Broker execution supports paper and live modes. Research results are not broker
fills, and paper evidence is not live validation.

Reviewed against the code on November 4, 2026. Enabled pairs, account settings,
worker health, and experiment results are runtime state, not guarantees in this
README.

## Application pages

| Page | Purpose |
| --- | --- |
| Daily Brief | Market context and setup information. A high setup score does not authorize a trade. |
| Live Trading | Trading activity, positions, and bot status. Check the account mode. |
| Performance | Recorded account and trade performance. |
| Trade Journal | Entered trades, exits, order evidence, and reconciliation. |
| Research Results | Strategy/ticker research outcomes and activation review. Hypothetical results are separate from broker fills. |
| Research: Exit Lab | Saved bucket-specific baseline/candidate comparisons, capture health, and policy history. Opening the page does not run backtests or change policies. |
| Learning Hub | Strategy lessons, charts, Coach Celo, practice, replay, progress, glossary, and log-reference material. |
| Settings | Strategy/pair permissions and account configuration. Permission does not bypass execution or risk checks. |

Learning coverage varies by strategy and version. Recorded examples and authored
teaching examples must remain distinguishable. Lessons are not profitability
evidence.

## Strategies and execution

Use Settings for current permissions rather than a static enabled-strategy list.
The authoritative implementation references are:

- [Strategy catalog](config/strategy_catalog.py): IDs, versions, scope, implementation routes, and observer/execution distinctions.
- [Research order specifications](config/research_order_specs.py): research-derived strategies with order-facing implementations.
- [Pair policy](config/research_pair_policy.py) and [admin overrides](config/admin_strategy_overrides.py): pair-specific policy and approval controls.
- [Entry checks](trading/entry/) and [position management](trading/position_manager/): order safeguards and open-position handling.

The catalog includes native strategies, contextual observers, and registered
research-derived execution routes. Catalog membership is not the same as being
enabled. Research observation does not grant order authority. Approval still
requires an implemented execution path and applicable safeguards.

Exits are strategy-specific. Not every strategy uses a 30-minute timer or the
same profit trail. Consult the implementation and the policy recorded for the
position. A research comparison does not silently replace a deployed exit.

## Specialized strategies and tickers

This is the implemented catalog as of November 4, 2026, not a list of currently
enabled trades or a claim of profitability. Versions are separate implementations,
even when their strategy names are similar. Account permission, integrity,
contract, and risk checks still apply.

### Ticker-specific execution implementations

| Strategy | Specialized ticker(s) | Version | Strategy ID |
| --- | --- | --- | --- |
| Opening-Range Pullback | TSLA | 2.0.0 | `V2_ORB_PULLBACK` |
| Trend Continuation | SPY | 2.1.0 | `V2_SPY_TREND_CONT` |
| Trend Continuation, QQQ route | QQQ | 2.1.0 | `RESEARCH_QQQ_TREND_V2` |
| Afternoon Fair Value Gap | SPY | 2.1.0 | `V2_SPY_AFTERNOON_FVG` |
| Failed-Range Recovery | SPY | 2.1.0 | `V2_FAILED_OR_BREAK_VWAP_REVERSION` |
| Two-Leg Trend Pullback | TSLA | 2.2.0 | `V2_TSLA_TWO_LEG_TREND_PULLBACK` |
| VWAP Pullback | AMZN | research.1 | `V2_VWAP_PULLBACK` |
| VWAP Pullback, 10:30 Displacement | AMZN, TSLA | 0.2.0 | `CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG` |

Scopes above come from the catalog's base tickers and research order specs'
explicit ticker restrictions. They are not a substitute for the current
account's approved pair inventory. The SPY Trend and 10:30 Displacement catalog
entries have paper-only defaults; any live eligibility must be checked through
the account-specific authorization path, not inferred from this table.

### Broader strategies with pair-specific approval

These implementations are not assigned a fixed execution ticker list in their
registry entries. Research and approval determine the exact strategy/ticker pair;
an empty static ticker set does not mean every ticker is enabled.

| Strategy | Version | Strategy ID | Static ticker scope |
| --- | --- | --- | --- |
| Trend Continuation | research.1 | `V2_TREND_CONT` | SPY and QQQ are recommendation targets, not blanket execution permission |
| Afternoon Compression Breakout | research.2 | `V2_AFTERNOON_COMPRESSION_BREAKOUT` | Pair-specific |
| Gap Fill | research.2 | `V2_GAP_FILL_RTH` | Pair-specific |
| Afternoon Reversal | research.1 | `V2_AFTERNOON_REVERSAL` | Pair-specific |
| ORB RSI/MACD Short | research.2 | `V2_SPY_ORB_RSI_MACD_SHORT` | Pair-specific; the legacy SPY ID is not a ticker restriction |
| Impulse Anchored VWAP Pullback | research.2 | `V2_IMPULSE_ANCHORED_VWAP_PULLBACK` | Pair-specific |
| Context-Filtered ORB, ATR10 execution variant | 0.1.0.research.2 | `RESEARCH_CTX_ORB_ATR10_V2` | Pair-specific |
| Failed-Range Recovery, research-derived execution variant | 2.1.0.research.2 | `RESEARCH_FAILED_RANGE_V2` | Pair-specific |

### Contextual observation variants

These entries are marked observation-only in the static catalog. Their listed
tickers are base study scopes, not a statement that collection is limited to
those names or that orders are enabled. Explicit pair approval and runtime
routing must be checked separately, including any paper execution adapter.

| Strategy | Base study tickers | Version | Strategy ID |
| --- | --- | --- | --- |
| Context-Filtered ORB, NR7 / Inside Day | AMZN, QQQ, SPY, TSLA | 0.1.0 | `CTX_ORB_NR7_OR_INSIDE` |
| Context-Filtered ORB, ATR10 | AMZN, QQQ, SPY, TSLA | 0.1.0 | `CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG` |
| VWAP Pullback, 1-Hour KER | AMZN, QQQ, SPY, TSLA | 0.1.0 | `CTX_VWAP_PULLBACK_KER10_LONG` |
| 1-Hour Bollinger / Keltner Squeeze | QQQ | 0.1.0 | `CTX_1H_SQUEEZE_MACD_LONG` |

For the actual enabled list, use Settings. Keep this catalog table synchronized
with `config/strategy_catalog.py` and `config/research_order_specs.py` when
versions or ticker restrictions change.

## Research and data boundaries


Keep evidence separate by strategy, ticker, code/policy version, account, and
paper/live mode. Distinguish historical replay, forward observations,
hypothetical shadow exits, and broker-confirmed fills.

Research Results contains setup and contract-study evidence. Exit Lab reads
persisted experiment summaries and loads details on demand. A page or worker
module existing does not prove collection is running. Check worker health,
last successful collection time, coverage, and exact missing-input reasons.

Missing candles, quotes, or structural levels are data gaps, not proof of a win
or loss. Recovered observations must retain their provenance rather than being
described as available at the original decision. Small or incomplete samples do
not establish an improved exit.

Local paid-data studies and generated artifacts are excluded from normal staging
by [deploy.sh](deploy.sh). Runtime research capture also exists in application
directories. See [research documentation](research/README.md) for that workspace.

## Code map

| Location | Responsibility |
| --- | --- |
| `trading/loop/`, `scanner/`, `strategy_router/` | Scheduling, scanning, and setup routing |
| `strategies/`, `config/` | Implementations, catalog, and configuration |
| `trading/entry/`, `broker/`, `risk/` | Contracts, orders, and safeguards |
| `trading/position_manager/` | Position monitoring and exits |
| `trading/research_collection.py`, `trading/research_bar_capture.py` | Research observations and candle capture |
| `database/`, `signal_journal/` | Persisted records and decision evidence |
| `api/`, `frontend/` | FastAPI endpoints and React interface |
| `api/routes/exit_lab.py` | Exit Lab API |
| `frontend/src/components/learning/` | Learning interface and practice |
| `tests/`, `frontend/tests/` | Backend and frontend regression tests |

## Development and checks

Use an isolated development environment, not production account data or live
credentials. Inspect [configuration keys](config/env_keys.py),
[defaults](config/defaults.py), and [requirements](requirements.txt) before
starting the backend. Application startup can initialize background services;
it is not a read-only documentation preview.

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

Run checks from the repository root:

```bash
python tests/run_production_suite.py
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

The Python runner explicitly excludes tests requiring the separate research
workspace. Passing tests does not verify forward collection during an open
market session. Verify actual worker records separately.

## Deployment

Earnings checks use a best-effort Yahoo Finance calendar through yfinance,
not the unavailable Tradier fundamentals endpoint. Two background workers
fetch public ticker data without broker credentials. Successful results expire
after 15 minutes; failures retry after one minute. Pending, stale or incomplete
data remains unavailable, with a warning in system events. Unknown data does
not currently block entry. Existing blackout settings apply to returned dates.
Recent and upcoming dates are both required for company stocks; a provider-
verified ETF is marked not applicable. Dates can be estimates and can change.
This is not a guaranteed market-data service or proof of open-session coverage.

Use [deploy.sh](deploy.sh) for application releases. Review the diff and keep
unrelated work out. It runs the production Python suite, frontend lint and build,
stages its application allowlist, commits and pushes to GitHub `main`, checks the
server checkout, and pulls the release. It installs dependencies and service
configuration, restarts the dashboard, checks `/healthz`, and performs storage
retention. Run frontend tests explicitly using the command above as well.

The script requires configured EC2 SSH access. `CELO_KEY_FILE` selects the key;
`CELO_TEST_PYTHON` selects the local test interpreter. Never commit secrets,
private keys, account databases, or paid-data archives. Do not bypass failed
checks and call an application release complete.

Before reporting success, verify GitHub `main` and production commits match, the
served frontend belongs to the release, services are healthy, and the affected
user flow works. A push alone is not deployment verification.

Normal releases are blocked on weekdays from 09:30 through 15:59 Eastern,
including holidays and early-close afternoons conservatively. The guard uses
daylight-saving-aware time, not an exchange calendar. An explicitly authorized
emergency release can use `./deploy.sh --force-market-hours`. Checks run before
tests, publication, server update and restart. If the window closes during a
release, inspect GitHub and server state before resuming; do not claim deployment
completed. Automatic recovery of a failed health check remains available.

Document rollback first. The script attempts to restore the previous server
commit if health verification fails. That can leave GitHub and production
different and requires follow-up. Preserve history and use a corrective commit,
not a force-push, for repository rollback.

Deployment does not authorize live trading, orders, or risk-limit changes.

### Independent session capture

`celo-session-capture` records the explicitly configured `research_tickers`
regardless of positions or trading switches. Research > Data Coverage reads
persisted summaries; it does not run collection or calculations. The recorder
uses the production Tradier feed only, with a 04:00 to 20:00 Eastern target on
provider-confirmed market days, completed one-minute stock history and
timestamped stock snapshots. Broker order hours do not truncate this target.
Shortened-session or unavailable extended-hours intervals remain visible gaps,
not a claim that every missing minute is a feed outage.
Every listed option expiration is queued without DTE, premium, spread or strike
filters. Raw chain snapshots preserve all returned contracts, including invalid
quotes, provider Greeks and sizes. Requests rotate within a bounded budget.

This is **not a complete exchange tick archive**. Quote changes between polls
are unavailable. Option rotation can be slow; pending expirations, each
contract's quote validation, and refresh timestamps remain visible. Missing
stock minutes are unresolved gaps, not synthetic zero-volume candles.
Recovered history retains its receipt timestamp and is not forward evidence.
Archives and durable task checkpoints live in the user's `session_capture`
directory, separately from trading databases. Responses are compressed and
append-only. Capture stops explicitly when free space falls below 1 GiB.
No automatic data deletion, subscription purchase or trading changes occur.

Rollback: stop and disable `celo-session-capture` immediately if it competes
with trading for rate capacity, exceeds its resource caps, or reports storage
errors. Preserve the archive. Revert the capture/UI release with a corrective
commit through `deploy.sh`, never by changing strategy or risk settings. Verify
the application health, existing capture services and GitHub/production match.

Documentation-only changes require no application restart. Follow
[release rules](AGENTS.md) and report local and deployment status separately.
# Fast research capture integration

The existing `celo-holding-forward` service now runs
`python -m strategy_health.fast_capture --user admin` from the versioned application.
It does not submit orders, evaluate candidates or change trading settings.
The earlier `/opt/celo_holding_observer/20261014_v6/data` archives remain intact.

It discovers the current account/mode's saved broker trades, primary research
contract selections, alternative contracts and expiration-study selections using
read-only database connections. Each durable registration retains account, mode,
strategy, ticker, version, contract, origin, first discovery time and capture horizon.
Missing versions/policies are visible and do not magically become valid exit tests.
Copied metadata is explicitly a discovery-time snapshot, not verified entry-time
state. New experiment code can call `Registry.register` with an explicit horizon
covering both policies; doing so collects data only and cannot authorize evaluation.

Automatic registrations capture through the next verified session close plus
60 seconds, or a later saved deadline. This is a data-retention envelope, never
a replacement exit rule. Saved registrations continue across restarts and account
switches. All scopes remain separate even when they share a raw market quote.
Expired registrations and archived observations are retained, not rewritten.

The worker rotates up to 20 contracts per request, at most one request every five
seconds, backing off on failures and provider quota pressure. It does not drop
contracts above 20. More contracts mean slower per-contract coverage, explicitly
reported as pending receipts, stale receipts and measured wall-clock gaps. The
five-second interval is not a promise of five-second coverage for each contract.
Raw quote timestamps, sizes and provider Greeks are preserved. These are sampled
market observations, never broker fills or a tick-complete tape. Broad universe
capture remains independent and unchanged.

Research > Data Coverage and Exit Lab read the saved capture report only. The
UI cannot start a worker, evaluate a strategy or modify a policy. A stale worker
report is flagged after 90 seconds. Discovery-limit and missing-input failures
remain visible; the source scan is bounded and never called a complete inventory
when it exceeds that bound. No prior quote is backfilled into a missing interval.

Rollback: on capture crash loops, quota starvation, source database contention or
unacceptable resource use, stop only `celo-holding-forward`. Restore its saved
`/etc/systemd/system/celo-holding-forward.service.pre-integration` unit, reload
systemd and restart that service to resume the original observer. Preserve both
archives. Revert the capture integration with a corrective commit and `deploy.sh`
before declaring a source rollback complete. Never change trading switches,
exit policies or risk limits as part of this rollback. The service backup is made
once before the first integration deployment and is not overwritten on later releases.
