# Research capture repair

Production probes found absent Alpaca minute candles which Tradier supplied:
COIN11:59, PANW12:19, QQQ12:09 and TSLA11:58 Eastern on November3.
The existing research exit reader did not request a second source except for
Compression. It finalized missing-bar attempts after its five-minute grace.

Research exit and profit-observer reads now try a single Tradier session read
when primary completed-session minutes are absent. Only complete, duplicate-free,
valid OHLC replaces the primary frame. No bars are fabricated or sources merged.
Append-only research_bar_recoveries records account, event bars, request/receipt
times, missing primary minutes and acceptance/error. Old outcomes stay untouched.
Native15m EMA collection stays unchanged. Trading order evaluation is unchanged.

Contract selection retains the exact existing premium, spread and expiry rules.
New screen_counts distinguishes premium too low/high, non-OTM, spread, invalid
price, missing symbol and request errors. Historical generic filtered values are
not rewritten. Fresh NFLX0-7DTE OTM options were below the1.50 minimum. Testing a
lower-premium profile needs separate approval and separate evidence.

Run audit_research_capture_health with an explicit user to emit all configured
tickers and exact strategy/version/account/mode buckets. Counts are attempts,
not counts of missing individual bars and not profitability judgments.

Deploy only after capture, session-close, worker-isolation and risk regression.
Check broker positions and orders before dashboard restart. Verify recovery
records from the running worker during the open session, separately from tests.

Rollback: revert this release and restart dashboard after reconciliation; leave
the additive evidence table and historical records intact. Revert if recovery
causes exceptions, stalls workers, accepts old/invalid bars or changes execution.
No destructive migration, trading switch, exit-policy or risk-setting change.
Historical late entry/close-quote gaps cannot be repaired by inventing quotes.
