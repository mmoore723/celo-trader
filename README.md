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

Document rollback first. The script attempts to restore the previous server
commit if health verification fails. That can leave GitHub and production
different and requires follow-up. Preserve history and use a corrective commit,
not a force-push, for repository rollback.

Deployment does not authorize live trading, orders, or risk-limit changes.
Documentation-only changes require no application restart. Follow
[release rules](AGENTS.md) and report local and deployment status separately.
