# Opening Momentum short trail — September 10, 2026

## Finding and predeclared experiment

`Simulator._tighten_trailing_stop` passes maximum high (`best_price`) to both
sides. OpeningMomentum's short branch adds 2 ATR to that value. A declining
stock therefore need not tighten the short stop. Its favorable extreme is
the minimum low (`worst_price`). Gap Fill shares this path and is queued for
its own fidelity review. No paper/live rules are changed by this experiment.

Keep the original protocol immutable. On each newly stamped bearish Opening
Momentum candidate, collect a separate low-water variant with the same entry,
contract, initial stop, 14-bar simple true-range average, 2 ATR distance,
skipped entry bar, next-bar tightening, 75-bar cap and session close.
Do not optimize ATR or entry thresholds against the sample. Both follow the
old stop during each bar; only a completed five-minute bar tightens the next
bar's stop. Observe the first completed one-minute stop touch; capture the
actual same-contract option bid afterward. Do not assume a stop-price fill.

Only compare candidates priced in BOTH protocols, on the same contract and
entry ask/time, with commissions and conservative price friction. Show paired
coverage, mean/median improvement, PF, P&L and drawdown; unpaired exits cannot
establish improvement. Missing/stale prices stay missing. Existing observations
and historical results are not relabeled. Later dates remain prospective
validation; no profitability or promotion claim follows from synthetic tests.

## Ten primary sources checked before changing the observation rule

1. [Alpaca orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca):
   favorable trailing reference is highest for sells, lowest for buys.
2. [IBKR trailing orders](https://www.interactivebrokers.com/en/trading/ordertypes.php?m=trailingModal):
   buy trails mirror sell trails; unfavorable movement does not loosen stops.
3. [Schwab short selling](https://workplace.schwab.com/story/ins-and-outs-short-selling):
   short-position buy stops trail the stock's lowest price.
4. [QuantConnect trailing orders](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-types/trailing-stop-orders):
   buy-stop levels descend as prices fall; gap fills can be worse than stops.
5. [Fidelity ATR](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr):
   ATR measures volatility, not direction. Its Wilder smoothing differs from
   this frozen engine's simple average; changing smoothing is out of scope.
6. [TradingView strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/):
   final bar highs/lows are unavailable before close; avoid future leakage.
7. [TradingView broker emulator](https://www.tradingview.com/support/solutions/43000786181-broker-emulator/):
   include commissions and slippage, not idealized frictionless fills.
8. [FINRA stop risks](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets):
   stop triggers do not guarantee execution prices, especially during volatility.
9. [Fidelity order FAQ](https://www.fidelity.com/trading/faqs-order-types):
   trigger basis and market-data processing matter; stop and limit differ.
10. [QuantConnect equity fill model](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/equity-model):
    rejects stale stop-fill data and treats buy trailing updates using lows.
