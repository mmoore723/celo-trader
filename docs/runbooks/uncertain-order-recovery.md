# Uncertain order recovery

Status: deployed on 2026-09-03 at 10:36 PM ET for the existing Alpaca adapter. Production remains in paper mode. This does not select another broker, enable live trading, or promote strategies.

## What changes

`Save intent → submit once → capture broker fills → commit fills + journal + cursor → reconcile remainder`

An HTTP timeout is not a rejected order, and an accepted cancellation is not a confirmed cancellation. The bot retains the original client/order IDs across restarts. While an order remains unresolved, another order for that account/contract is not submitted. Confirmed partial fills remain visible and are managed at their actual size once the resting remainder is resolved.

The original quote selection, approved entry ceiling, no-market-chase entry policy, and explicit emergency-exit fallback remain in place. Once an order partially fills, it stays at its existing limit until resolved; it is not price-replaced while partially filled.

## Durable state and accounting

- `execution_recovery` is an additive SQLite table in the existing **per-user, per-mode** trades database. It stores sanitized order requests/responses, original decision/exit context, and cumulative applied quantity/notional. No API tokens are stored.
- The recovery account key is verified against Alpaca's account endpoint. Existing key-based journal labels are accepted only when they match the current credential; journal labels/settings are not rewritten.
- An OS lock and a unique active account/contract row protect concurrent requests. A process restart releases the OS lock but does not erase the unresolved record.
- Each confirmed fill increment and its accounting cursor commit together. Partial exits atomically create a closed child and reduce the open parent's quantity. Replay does not duplicate entries, exits, P&L, or daily-summary totals.
- Existing closed history is not reinterpreted. This release handles newly recorded execution attempts, not a retrospective correction of old trades.
- Fill price/quantity come from broker responses, never planned limits. When fills race a replacement, individual FILL activities and their unique execution IDs resolve the parent/child quantities; pagination is bounded and incomplete evidence remains pending.
- Routine exit, stage-1 exit, manual close, and panic use the same recovered-fill accounting. Stage-1 completion is recoverable from the journal after a crash.
- A failed broker position/order snapshot is unknown, not an empty account. Exit evaluation waits for broker-position availability in that failure case.

## Automatic recovery

The normal loop and startup reconciliation check pending attempts. After hours, unresolved executions are checked on the short loop rather than left until market open. Recovery can query the saved client ID after a lost submission response, follow replacement IDs, request cancellation of a resting remainder, and apply newly confirmed fills. It never sends a new entry or uncapped fallback by itself.

If reconciliation changes the position during a retry request, that request does not submit another order from its stale size. The next evaluation reads the corrected quantity.

Broker unavailability, invalid/missing execution prices, conflicting quantities, unmatched accounts, or incomplete activity history keep the attempt pending and produce an actionable log/position-alignment issue. Do not delete the pending row to force a retry; that removes duplicate-order protection.

## Operator checks

1. Check the current authenticated broker connection status, then the latest `order`/reconciliation events.
2. Inspect the active database path returned by `get_db_path()` for the authenticated user. For the current admin paper account it is `/opt/celo_trader/user_data/admin/trades_paper.db`, not the repository-root snapshot.
3. Read `execution_recovery` rows where `active=1`; compare their saved IDs with the broker's order and FILL activity responses.
4. If the broker cannot confirm terminal status or supplies conflicting evidence, leave the record intact and investigate the broker account. Do not fabricate a fill, mark the account flat, or submit another order to clear the alert.

## Verification and rollback

### Verified release — 2026-09-03

- Application commit: `fa9503d705841b0d25c33dafcd847958e896a719`; previous release: `68515499de324e40a83e9c13e6fe3448c22e9d4b`.
- Local backend suite: **596 passed**, including **22 new recovery tests**. Final focused safety rerun: **35 passed**. Focused production-server suite before restart: **75 passed**.
- Active paper database backed up consistently before deployment to `/opt/celo_trader/user_data/admin/release_backups/pre-fa9503d-20260904.sqlite` (file mode `0600`). No credentials were copied into the backup.
- At 10:41 PM ET, the deployed service and public health endpoint were healthy. Authenticated **Alpaca Paper** and **Tradier Production** checks both returned connected; Tradier Sandbox remained unused.
- Broker remained Alpaca, paper mode and bot running state were preserved, and settings/credential fingerprints matched the pre-deployment values. Broker positions, open orders, and pending recovery records were all zero. No post-restart ERROR/CRITICAL system events were found in the latest 300 records.
- No test orders were submitted, no existing historical trades were rewritten, and no frontend or unrelated research changes were deployed. A market-session execution trial remains outstanding.

### Repeatable checks

Offline test suites: `tests.test_execution_recovery`, `tests.test_execution_recovery_faults`, and `tests.test_execution_recovery_integration`. These use temporary databases and mock broker endpoints; they do not place orders. Full backend suite: `python -W ignore::ResourceWarning -m unittest discover -s tests -q`.

Before deployment, verify paper mode and broker, fingerprint settings/credentials, confirm no broker positions/open orders, and record the previous Git revision. Run focused tests on EC2 before restarting. Smoke-test service/public health and authenticated broker checks afterward. No frontend bundle change is required.

Rollback is a code checkout to the verified previous revision and service restart **only when no new unresolved executions or positions exist**. Do not delete the recovery table or restore an older trading database over newer fills. If trading has begun, reconcile the pending orders first; the previous release cannot manage this new durable ledger.

Read-only verification is not a market-session execution trial and does not establish profitability or paper/live fill equivalence.

## Broker sources

- [Alpaca order lifecycle and client-provided IDs](https://docs.alpaca.markets/us/docs/orders-at-alpaca).
- [Querying orders by client ID](https://docs.alpaca.markets/us/docs/working-with-orders).
- [Individual account FILL activities and cumulative quantities](https://docs.alpaca.markets/us/docs/account-activities).
- [Order-specific FILL queries and pagination](https://docs.alpaca.markets/us/reference/getaccountactivitiesbyactivitytype-1).
