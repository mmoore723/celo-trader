# Context ORB NR7 / Inside Day — quote-based exit tracking

Reviewed September 10, 2026. Observation only; execution sources and hashes unchanged.

Original source: /Applications/celo_trader/research/engine/context_option_replay.py,
structural_exit_for_signal, option_path_outcome and size_outcome.
Midpoint rule uses a completed one-minute CLOSE, not intrabar high/low.
Long invalidates at or below the opening-range midpoint; short at or above.
The explicitly documented original intraday fallback is 15:55 ET.
Targets use the actual option BID relative to the entry ASK: +30% and +100%.
For quantity one there is no partial sale. For quantity >=2, floor(quantity/2)
is sold at +30%; the remainder at +100% or structural fallback.

New prospective evidence records the one-contract runner and a separately
labeled two-contract split, never a fictional half-contract fill. Both use
the application's conservative slippage and per-contract fees, not the old
report's .35 fee default. Existing timer results remain separate.

Research boundary stamps only newly observed NR7 candidates with source hash
and policy. No locked entry source is edited. All collected ticker candles
continue through the isolated cross-ticker observation adapter. No cooldown,
allocation cap, order setting, or strategy permission changes.

The tracker polls fresh same-contract quotes and stores first +30% milestone,
first +100%/midpoint/EOD runner close, and compact quote count/timestamp.
It is sampled evidence, not a continuous tick replay; brief target touches
between polls can be missed. The UI discloses this. Missing underlying minutes
prevent crediting a target before knowing whether the midpoint invalidated.
Entry ask must be within its entry minute; entry minute is skipped because
its OHLC may predate the quote. Unlike a legacy replay edge case, no target
can override a structural decision at or before that target quote.
These causal differences are explicit, not relabeled historical performance.
Structural exit requires a quote within one minute, matching the saved replay.
Early-close sessions remain an unresolved calendar-specific limitation.

Acceptance covers long/short close-only invalidation, targets/partial arithmetic,
integer quantities, stale/wrong quotes, gaps, late entry, restart/isolation,
overlapping candidates sharing quotes, additive migration and UI separation.
No claim that the strategy is profitable or ready to promote.
