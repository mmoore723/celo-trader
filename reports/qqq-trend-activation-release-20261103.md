# QQQ Trend activation

Previous production source: b89455d1. Scope: QQQ Trend Continuation 2.1.0.

New execution identity RESEARCH_QQQ_TREND_V2 reuses the exact native entry
engine used by cross-ticker research with real QQQ candles and independent
deduplication state. Original SPY execution and historical evidence are untouched.
The default remains a 30-minute hold. Explicit selected timers and contract
policies are frozen into new entries. No strategy activates on deployment.
Configuration may match paper/live, but this is not live profitability validation.
Risk limits and live-trading status stay unchanged.

Validation covers signal parity, ticker/account isolation, settings persistence,
source-to-execution mapping, chosen timer, mandatory session exits, quote outage,
partial fills, duplicate orders and recovery. Server tests and fresh zero-position
reconciliation are required before restart. Never submit a smoke-test order.

Rollback triggers: integrity errors, incorrect mapping/settings, failed
reconciliation, regression failure or repeated activation API errors.
Before anyone activates this route, revert this scoped release and restart after
zero-position/order reconciliation. If new-route positions exist, do not remove
their exit implementation. Keep their frozen policy running until closed, and
coordinate reversal of future-entry permission with the owner. Never reset risk,
delete historical trades or change live mode as rollback.

The unrelated pending capture storage patch is not included.
