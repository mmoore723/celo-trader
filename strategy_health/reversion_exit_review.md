# VWAP Reversion exit evidence — September 10, 2026

Scope: V2_VWAP_REVERSION_RTH. Record the original entry's VWAP target and
4-ATR stop, not today's latest VWAP or a fixed 2R target. There is no trailing
method in the source. The runner selects the 15:55 session candle and inherits
the simulator's 75-bar cap. Observe completed five-minute bars causally,
skip the entry candle, prefer stop on ambiguity and flatten at 16:00.

Sources: research/engine/strategies/vwap_reversion_rth.py, its _session,
_vwaps, _atr and _ema helpers, research/engine/simulator.py,
research/jobs/run_vwap_reversion_rth.py, trading/tested_strategy_research.py.
Hash the source and serialize default configuration, including time values.
Unknown proof, missing bars and expired quotes cannot become priced results.
Keep the existing 90-minute check separate from actual exit evidence.

Tests generate genuine long and short signals through the unchanged default
engine, followed by stop, target and session outcomes. Runtime aggregation
preserves volume because VWAP depends on it. These are synthetic fidelity
tests, not investment performance or historical profitability evidence.
Forty overlapping recorded plays are priced independently without allocation
limits; restart, account, strategy and target-reason isolation are tested.

Entry audit finding: with positive ATR, the 2.5-ATR band reclaim and minimum
1.5 reward/risk against a 4-ATR stop leave the close between 2.4 and 2.5 ATR
from entry VWAP. The flat-EMA condition also applies. This algebra explains a
narrow eligible region; it does not prove why a particular day lacked signals.
The original engine additionally emits at most once per ticker per day.
No new cooldown is added here. That source restriction needs an explicitly
versioned research comparison to satisfy the user's all-opportunities intent,
not silent alteration of this original-rule measurement.

Next: quantify price-band/EMA/once-per-day rejection counts on real collected
sessions; compare all-opportunity variants and dynamic exits with source
review, predeclared changes, realistic option costs and untouched later dates.
No paper/live rules, switches, historical results or order routes changed.
