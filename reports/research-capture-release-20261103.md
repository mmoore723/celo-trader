# Research candle capture correction

Previous production bc6298ba. Actual records repeatedly report the same 104 BABA
and 54 COIN primary-feed gaps, despite accepted full Tradier sessions less than
a second later. Research always started with Alpaca and wrote full recovery
records repeatedly. This is not proof that 104 new minutes were lost each scan.

Research now requests Tradier first. Only validated complete sessions are cached,
scoped by database, account, ticker and exact minute, bounded to 128 entries.
Forming candles are removed. Receipt timestamps stay attached to cached frames.
The next minute requires a new request. Restart clears cache and fetches again,
never treating old cached data as current. Observations are appended with direct
source provenance; old recovery evidence is unchanged. Incomplete/corrupt/failed
responses are not cached and fall back to the existing recovery checks.
Trading entry/exit logic, risk, grants and live status are unchanged.

Verify tests for feed failure, invalid bars, duplicate timestamps, incomplete
sessions, scope isolation and cache expiry. Verify runtime integrity and broker
reconciliation before restarting. Verify fresh direct-source persisted records
from the running worker separately from simulations.

Rollback on missing fresh records, increased failure frequency, integrity errors
or service failure: revert this release including runtime-review selector, then
restart safely. No database migration or history deletion. Existing storage-budget
warnings elsewhere are a separate outstanding issue and not fixed by this release.
