# Paper P&L versus saved Tradier quotes

The paper broker's P&L is an accounting result, not proof that the same prices
were available from Tradier. The read-only quote-realism audit therefore keeps
two separate views:

- recorded Alpaca paper P&L;
- a research replay that buys at the saved Tradier ask and sells at the saved
  Tradier bid, with the configured per-contract passthrough-fee stress.

New rows use the exact Tradier quote saved within two minutes of submitting the
exit. Entry quotes must also be within two minutes of the recorded entry. Older
rows did not save the exact exit field. They may use only the nearest earlier
exact-contract Tradier mark within 120 seconds, and are labeled **legacy nearby
mark**. That legacy value is diagnostic evidence, not a claim that Tradier would
have filled the order at that price. Missing, stale, crossed, wrong-contract,
unknown-source and non-finite prices remain unmeasured.
`observed_at` is the application's receive time and does not prove the exchange
timestamp, so the audit never calls these prices guaranteed fills.

Run from the project root:

```sh
venv/bin/python -m research.jobs.audit_paper_quote_realism \
  --database user_data/admin/trades_paper.db \
  --settings user_data/admin/settings.json \
  --start 2026-08-14 --end 2026-09-05
```

The job uses one read-only, account-scoped SQLite snapshot. It does not import
the trading runtime, call either broker, change settings, alter historical rows,
place orders, or make a launch decision. The result reports exact and legacy
coverage separately, plus strategy/ticker PF. Extra slippage and the $10 monthly
subscription are not allocated; the saved spread is paid by entering at ask and
exiting at bid. Therefore even the quote-aligned result is not a live guarantee.
