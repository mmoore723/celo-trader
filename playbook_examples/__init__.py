"""
playbook_examples/__init__.py — Mines REAL historical examples of each of
the 8 strategies firing, for use on the Playbooks education page.

Why this exists (2026-06-20 audit)
───────────────────────────────────
The Playbooks page previously illustrated every strategy with _gen_orb_scenario()
in dashboard.py — randomly generated, fabricated candles. That's a real
credibility problem for something people pay to learn from: a synthetic, made-up
chart undermines trust in a strategy you're asking someone to pay for.

This module walks REAL historical 5-min bars through the SAME indicator-building
and strategy-evaluation functions the live bot uses every tick (_build_indicator_frame
+ the eight _eval_* functions in strategy_router.py), finds genuine fire events, and
classifies what actually happened afterward (favorable move / reversal / chop) —
so Playbooks can show a real ticker, on a real date, doing a real thing.

We deliberately do NOT call route_signals() directly — it gates on check_kill_lock(),
which reflects the LIVE bot's current trading-halt state. That guard is meaningless
for offline historical analysis and would silently return zero signals if the live
bot happened to be kill-locked at the moment someone re-runs this script. Calling
the eval functions directly bypasses that, which is correct here.

Usage
─────
  Run standalone to (re)generate the cache file:
      python -m playbook_examples
  (Was `python playbook_examples.py` before this 2026-08-01 file-size-cleanup
  split from a flat file into this package — a plain script no longer exists
  at that path, so the invocation changed to the package form. See
  playbook_examples/__main__.py.)
  Or call mine_all_examples() from the dashboard (wired to a "🔄 Regenerate
  examples" button) so re-running doesn't require a terminal.

  Requires network access to Alpaca (same credentials as the live bot, via
  .env). This will NOT work in an offline/sandboxed environment — it needs to
  run wherever the bot itself normally runs.

Output
──────
  playbook_examples.json — keyed by strategy_id, each holding a list of
  {ticker, date, direction, confidence, rvol, outcome, signal_idx, entry_idx,
   exit_idx, bars: [real OHLCV window]} records ready for charting.

Known gap (as of 2026-06-20)
─────────────────────────────
MID_BRK and AFT_REV have never fired in any real session logged so far
(confirmed via trades_paper.db system_events — zero narration for either).
Until they fire for real, mine_all_examples() returns fewer than
max_examples_per_strategy for those two, or none at all on a fresh run. The
Playbooks page MUST render an honest "no real example yet — strategy hasn't
fired in live trading" state for any strategy missing from the output rather
than fabricating one. Do not special-case these back into synthetic data.

Split (2026-08-01, file-size cleanup) out of the old single
playbook_examples.py into rvol_gates.py, evaluators.py, outcome.py,
mining.py, and io.py; no logic changed, only relocated. This package has
zero external Python consumers (nothing else in the repo does `from
playbook_examples import ...` or `import playbook_examples`) — it is only
ever run standalone or called from the dashboard's regenerate button — but
every public name is still re-exported here for completeness/safety.

NOTE: as of this split, importing this package fails at runtime with
`ImportError: cannot import name '_eval_inst_orb' from 'strategy_router'`
— a pre-existing bug in strategy_router.py's own exports, confirmed
unrelated to this refactor (same finding already noted in the config.py
and signals.py split commits this session). Out of scope for a pure
file-size split; flagged here for visibility since this package is the
one most directly affected by it.
"""

from playbook_examples.evaluators import _EVALUATORS, _SWING_CONTEXT_PAD
from playbook_examples.rvol_gates import _FIXED_RVOL_GATES, _real_rvol_gate
from playbook_examples.outcome import _OUTCOME_LOOKAHEAD, _FAVORABLE_MOVE_PROXY, _classify_outcome
from playbook_examples.mining import mine_strategy_examples
from playbook_examples.io import EXAMPLES_PATH, mine_all_examples, save_examples, load_examples

__all__ = [
    "_EVALUATORS", "_SWING_CONTEXT_PAD",
    "_FIXED_RVOL_GATES", "_real_rvol_gate",
    "_OUTCOME_LOOKAHEAD", "_FAVORABLE_MOVE_PROXY", "_classify_outcome",
    "mine_strategy_examples",
    "EXAMPLES_PATH", "mine_all_examples", "save_examples", "load_examples",
]
