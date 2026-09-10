# Hourly Squeeze exit measurement — September 10, 2026

The unchanged strategies/context_strategy_observers.py requires a completed
hourly squeeze release, positive/rising MACD histogram and at least36 hourly
bars. It records the entry-visible SMA20; the stop is not a rolling future SMA.
The existing isolated cross-ticker observer uses actual ticker candles.

The saved /Applications/celo_trader/research/engine/context_option_replay.py
structural_exit_for_signal uses the first later completed regular-session
hour whose close is strictly below that frozen SMA20. option_path_outcome
and size_outcome use a +150% option-bid target:2.5 times the entry ask, not
1.5 times. All contracts exit together; there is no ORB-style +30% partial.
No source entry, catalog permission, live/paper limit or user switch changes.

The original replay explicitly imposes15:55 because the suggestion did not
specify overnight holding. This remains a labeled test assumption, not proof
of an optimal hourly holding period. The last half-hour cannot become a full
hourly stop. Early-close sessions remain a calendar-specific limitation.

New prospective records carry the locked source hash and separate protocol.
Entry ask must be from the entry minute. Each completed post-entry hour needs
all60 one-minute constituents; missing bars block premium target credit once
that hour could have stopped the position. A five-minute bar-arrival grace
precedes an unmeasurable result. Before hour close, no hourly stop exists.
First structural decisions persist before quote I/O; actual bid must arrive
within one minute including latency. Profit targets use fresh same-contract
sampled bids strictly after entry. Target touches between samples may be
missed, disclosed in the UI. No implied continuous tick coverage.

One-contract net costs include .01-per-side slippage and .65-per-side fees;
missing prices never become zero-profit trades. Quote milestones stay compact
in the shared premium table with partial fields unused; no extra table/data
duplication. All overlapping candidates may be measured, sharing fetches.
Actual measured exits remain separate from timer comparisons and historical
PF. Tests include genuine source/META signal, frozen hourly close, incomplete
hour cap, gaps, threshold arithmetic, losses, concurrent plays, isolation,
restart/quote recovery and matrix/UI separation. Profitability remains unproven.
