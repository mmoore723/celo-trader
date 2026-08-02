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
