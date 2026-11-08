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

The worker rotates up to 600 contracts per request, at most one request every five
seconds, backing off on failures and provider quota pressure. It does not drop
contracts above the batch limit. Contracts past their OCC expiration date in
Eastern time stop polling but remain visible with an explicit expiry reason;
the expiration day itself is retained. More contracts mean slower per-contract coverage, explicitly
reported as pending receipts, stale receipts and measured wall-clock gaps. The
five-second interval is not a promise of five-second coverage for each contract.
Raw quote timestamps, sizes and provider Greeks are preserved. These are sampled
market observations, never broker fills or a tick-complete tape. Broad universe
capture remains independent and unchanged.

The collector uses Tradier's market-data-only POST /v1/markets/quotes endpoint
for bulk quotes, avoiding long GET URLs. It cannot POST to any other endpoint.
Calendar and other data requests remain GET-only; rate reserve and backoff are
shared by both methods. No order endpoint or new subscription is introduced.
All 540 current unexpired symbols returned in 0.202 seconds in an after-hours
provider probe on November 8, 2026. This is not market-session latency validation.
The 600-symbol ceiling bounds payload size; larger inventories rotate without
being silently dropped. If bulk requests fail or overload the collector, restore
the previous 300-contract GET batch through a corrective deploy.sh release, retaining all registrations and
observations. Never relax experiment coverage requirements to hide slow collection.

### Native exit decision log

The position manager records its exit checks without changing their results.
Records include a unique management-cycle ID, account/mode/trade identity, saved
entry policy context, actual evaluator arguments, source quote clocks, observer
clock, before/after state, holds, exit reasons and validation skips. The broker
mark and Tradier quote are distinguished. TSLA giveback records the persisted
state it read and the state used by its pure decision helper.

`user_data/<user>/exit_decisions/decisions.sqlite3` is an append-only observation
archive, not a fill ledger. A bounded 32-event background queue writes it; order
execution never waits for SQLite. Snapshotting still has CPU cost. Frames and
large objects have explicit size limits, and incomplete snapshots are labeled.
Failed writes, dropped events and the last successful save appear in the separate
`health.json`. Counters are process-lifetime diagnostics, not historical coverage.
There is a 1 GB free-disk reserve. A forced process termination can lose queued
records; these logs alone do not establish complete native replay or fill timing.
No observation retroactively repairs old research evidence.

Rollback: set `CELO_EXIT_TRACE_DISABLED=1` in the service environment and restart
through the normal operational procedure, or publish a corrective deploy.sh
release removing the instrumentation. Preserve the archive. Roll back if the
instrumentation changes an exit result, causes a management exception, or creates
unacceptable decision latency. Disk/queue failures must leave exits running and
mark capture incomplete, never change a trading setting to conceal a gap.

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

### Paired exit accounting core

`strategy_health/paired_exit_accounting.py` is a pure, offline shadow-pricing
library. It does not enroll experiments, run automatically, submit orders or
change policies. Native and candidate adapters must supply verified exit intents;
this library does not yet implement those adapters or qualify a candidate.

Both branches use identical entry fills, contracts and quantities. Exit pricing
uses the first eligible observed bid after each intent, available size, explicit
fees and slippage. Partial exits conserve quantity. Source freshness and receipt
coverage extend through the later exit. Missing prices remain blocked, not zero
profit. Invalid or stale receipts cannot fill a coverage gap. Reported drawdown
is closed-trade equity drawdown, not intratrade mark-to-market drawdown.

Reports stay separate by account, mode, strategy, ticker, code version, experiment
and policy pair. All exit results are hypothetical, not broker fills. Uncertainty,
native decision validation, holdout and qualification remain separate unfinished
work. Unit tests cover costs, quantities, stale/late quotes, gaps, duplicates and
isolation. No observed profitability is claimed from synthetic tests.

Deployment rollback: remove the unused library in a corrective deploy.sh release
if it disrupts imports or regression tests. No migration or trading-setting
rollback is needed. Preserve saved evidence; no research runs are started by
shipping this code.

### Full-session scope and refresh timing

The session collector uses the explicit `research_tickers` universe, not the
trade journal or enabled strategy signals. On provider-confirmed market days it
targets completed stock minutes from 04:00 through 20:00 Eastern, stock quote
snapshots and every listed option expiration. It is not a complete exchange
tick tape; snapshots miss intervening updates and provider quotas limit rotation.

Research Data Coverage now shows observed option-chain refresh gaps, request
duration and refresh age by expiration. A successful chain receipt is not proof
that every contract had a fresh price. One response cannot establish a refresh
interval. Missing timing history displays as unmeasured, never zero delay.
New append-only `chain_refreshes` metadata survives restarts and deduplicates by
raw response ID. Existing history is not rewritten or silently relabeled.
This report is calculated by the background worker; opening the page only reads
saved results. Synthetic coverage checks include a full 960-minute day for the
23-name approved-universe fixture with no trade inputs. Actual session coverage
must still be verified during market hours.

Rollback: corrective deploy.sh release restoring the earlier summary and UI if
timing collection causes worker errors or excessive summary latency. Retain the
additive metadata table and raw archives; the old worker ignores that table.
This change does not alter subscriptions, exits, risk limits or trading switches.

### Native exit request evidence

The manager's full and partial exits now journal the exact broker-call arguments
and response under a shared action ID. Remaining position quantity, requested
sell quantity, reason, prices and order type are distinct from broker-reported
filled quantity. Timeouts never imply no fill; responses are not independently
reconciled fills. Logging disabled or unavailable leaves the original call,
arguments, return value and exception unchanged. Direct full-close calls outside
the manager also get a scoped capture context.

`strategy_health/native_exit_requests.py` converts these observed requests into
shadow-pricing intents. It validates account/mode/strategy/ticker/version,
entry-context fingerprint and contract, rejects incomplete evidence, separates
retries and requests after hypothetical liquidation, and blocks actual-versus-
shadow quantity divergence. It does not replace native decisions with a timer.
These records alone do not prove complete decision coverage. The adapter does
not enroll an experiment, qualify a candidate or alter production exits.

The source review is appended as `exit-action-capture-20261108.1`; historical
research artifacts and prior reviews are unchanged. Rollback uses
`CELO_EXIT_TRACE_DISABLED=1` and a normal service restart, or a corrective
deploy.sh release restoring the prior wrappers and matching runtime review.
Retain journals. Roll back if logging changes a broker argument/result or adds
unacceptable exit latency. Actual session latency and coverage remain pending.

### Structural supplement comparison

`strategy_health/structural_supplement.py` is an explicitly invoked offline
research evaluator, not a production exit policy. It selects only the configured
entry-level field and requires scoped evidence that the source was complete and
the level recorded before entry. Calls use a strict price breach below support;
puts mirror above resistance. Equality holds. No ATR or inferred-level fallback,
forming candle, indicator trigger or reconstructed historical price is used.

Forward underlying prints need source and receipt clocks, provider identity and
evidence IDs. Stale/future/recovered observations are rejected and counted;
duplicate source events cannot inflate coverage. Gaps through the later native
exit block the pair. This observes sampled last trades, not every exchange tick.

The orchestration function prices native actions with the paired accounting
model before composing the candidate. Native full exits already triggered keep
precedence. Earlier completed partial sales retain their size. A structural
breach overlapping an unfinished partial is blocked, not treated as a known
cancellation or fill. This intentionally leaves that execution case unmodeled.
Option-pricing failures and structural-input failures have distinct stage labels.

Synthetic tests cover call/put symmetry, late/missing/wrong-side levels, equality,
feed identity, duplicates, gaps, safety precedence, partial fills and paired
winner-to-loss outcomes. No archived trade cohort has been evaluated by this
release. Archive adapters, independent decision-coverage validation, approved
frozen specifications and prospective outcomes remain required before enrollment
or qualification. Installing the module does not start a worker or promote exits.
Rollback is corrective removal through deploy.sh; no trading-setting or database
migration rollback is needed. Retain all source evidence and prior reports.
