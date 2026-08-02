# Research Engine V2 — Evidence Before Orders

## Purpose

V2 is a clean, paper-only research engine built alongside the existing bot.
It does **not** replace the current order loop and cannot submit an order.
Its purpose is to answer one question honestly: does a precisely defined setup
have a repeatable edge after costs, on data it did not use for design?

Profit cannot be guaranteed.  What V2 guarantees is a reproducible decision
trail: a strategy is either supported by recorded evidence or it cannot be
promoted.

## Boundary

```text
market bars -> strategy (raw setup only) -> simulator -> immutable trade ledger
                                                    -> validation gates
                                                    -> paper-observation adapter (future)

existing bot --------------------------------------------------------> unchanged
```

Strategies do not query settings, place orders, mutate a database, or select
an option contract.  They receive bars and return either no setup or one
`Signal`.  The simulator owns fill assumptions and the ledger owns results.

The first data boundary is a chronological OHLCV CSV with a SHA-256 fingerprint.
That makes a historical result reproducible even if a provider later revises
its feed.  The first V2 baseline is `V2_TREND_CONT`: a transparent trend/EMA
plus fresh-range-breakout hypothesis with ATR-defined invalidation.  It is a
research baseline only, not a promoted replacement for the legacy strategy.

`scripts/research_v2/fetch_yfinance_csv.py` exports one explicit bounded
intraday snapshot while online.  It is a convenience source for rejecting
weak signal logic; the artifact is then tested offline.  It is not historical
options fill data and cannot be used to claim options profitability.

For authenticated historical equity data, `scripts/research_v2/fetch_alpaca_csv.py`
uses Alpaca only to create the same frozen CSV artifact.  It filters the
requested dates after fetch and does not expose the broker client to a V2
strategy or simulator.

Alpaca exports default to regular-session bars and drop an incomplete final
session.  Extended-hours data or a partial close can change the meaning of a
setup and must be an explicit research choice, never an accidental input.

## V2 contracts

| Component | Responsibility | Must not do |
| --- | --- | --- |
| `Strategy` | Turn only past-and-current bars into a signal | Fill an order or read future bars |
| `Signal` | Declare side, entry idea, stop, target, and feature snapshot | Claim a confidence is probability |
| `Simulator` | Next-bar entry, conservative stop/target handling, costs, MAE/MFE | Change strategy rules |
| `Trade` | Immutable realized result and provenance | Hide rejected/expired signals |
| `Validation` | Apply transparent pass/fail gates to in-sample and holdout results | Promote a strategy automatically |

## Promotion policy

A V2 setup progresses only in this order:

1. **Research** — raw strategy test on a design period.
2. **Holdout** — unchanged strategy is tested on a later, untouched period.
   V2's `run_walk_forward()` uses separate strategy instances and refuses to
   blend the two periods into a single flattering score.
3. **Portfolio** — compare the current portfolio with and without the setup;
   report displaced trades and net portfolio delta.
4. **Paper observation** — no automatic order; record live candidates and
   compare modeled versus executable option quotes/fills.
5. **Paper execution** — explicit human approval only after the above.

Default validation gates are deliberately visible configuration, not magic:
minimum completed trades, positive net expectancy after modeled costs, profit
factor above 1, bounded drawdown, and a positive untouched holdout.  They are
screening gates, not a promise of future profitability.

## What is intentionally deferred

Historical option bid/ask and fill quality are required before V2 can support
an options-profit claim.  The first simulator uses an underlying-price proxy
only to reject bad signal logic cheaply.  A future `OptionFillAdapter` will
replace that proxy for paper-promotion decisions; it must include quote time,
bid, ask, spread, chosen contract, and actual paper fill.

## Candidate reproduction contract

An externally sourced TradingView candidate is not eligible for research based
on a performance screenshot or a strategy name. It must have all of the
following recorded before implementation:

1. Saved Pine source with SHA-256 fingerprint.
2. `candidate_manifest.json` declaring symbol, timeframe, session, TradingView
   commission/slippage, Bar Magnifier, and calculation/fill settings.
3. Exported TradingView trade list for the same immutable bar dataset.
4. A V2 immutable trade ledger produced by the reproduction.
5. A trade-by-trade reconciliation report, including unmatched trades and entry
   price deltas.

`scripts/research_v2/validate_candidate_manifest.py` validates the manifest
and saved source hash. `scripts/research_v2/reconcile_tradingview_trades.py`
compares an exported trade list with a V2 ledger. A high match rate establishes
implementation fidelity only; the normal holdout and options-fill gates still
apply.

## Long-history collection

`fetch_alpaca_csv.py` accepts `--chunk-days` for long historical intervals.
Chunks are requested with exact non-overlapping calendar boundaries, merged in
chronological order, fingerprinted as one frozen artifact, and reject
conflicting provider revisions at a shared timestamp. This is required because
the provider's per-request bar limit cannot safely define a multi-year dataset.

```bash
python3 scripts/research_v2/fetch_alpaca_csv.py SPY \
  --start 2024-08-01 --end 2026-08-01 --chunk-days 90 \
  --output research_data/SPY_5m_2024-08-01_2026-08-01.csv
```
