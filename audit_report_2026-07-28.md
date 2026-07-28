# Celo Trader — code audit, 2026-07-28

Scope: signal generation math, the gate/confidence pipeline, entry execution,
exit/position management, risk/sizing math, and live-vs-backtest fidelity.
Depth varies by area — see the coverage note at the end. Two real, live-impacting
bugs were found and fixed during this session (RVOL and ADX); everything else
below is either already fixed, confirmed-not-a-bug, or a new lower-severity
finding from this pass.

## Fixed this session

### 1. RVOL read 0.0x on nearly every live signal (HIGH — fixed)

**Where:** `signals.py::compute_rvol()`

**What was wrong:** today's live bars are fetched at 1-minute resolution;
the 15-day historical baseline used to judge "is this unusual volume" is
fetched at 5-minute resolution (Alpaca's free tier can't return 15 days of
1-minute history). The old code matched bars to their historical baseline by
exact minute-of-day. About 80% of today's 1-minute bars landed on a minute
that no 5-minute historical bar could ever match, so RVOL came back `NaN`,
which downstream code displayed and scored as `0.0x`. The 20% that did match
were comparing one minute's volume against a five-minute historical average
— deflating RVOL roughly 5x even when it "worked."

**Impact:** confirmed live via `bot_tail.log` — RVOL read 0.0x on all 195
sampled log lines across 13 tickers on 2026-07-28. Cross-checked against
older logs: 100% nonzero on Jul 19/21/22, dropping to ~17% nonzero on Jul 23,
0% by Jul 28 — a progressive decay, not a single bad deploy (the code path
itself is unchanged since before Jul 22, so the exact trigger for the decay
is still not fully explained — see Open questions). Because RVOL feeds
directly into confidence scoring and several strategies' RVOL gates, this
was the dominant reason the bot placed zero real trades for roughly a week.

**Fix:** `compute_rvol()` now buckets every row (historical and today alike)
into 5-minute slots. Today's volume is summed cumulatively within its
current (possibly still-forming) bucket and compared against the historical
bucket's full average — apples to apples. Verified against a synthetic
mixed-resolution dataset (normal bars settle at 1.0x by bucket end; an
artificially 5x-hot bucket correctly climbs to 5.0x) and against live data
(0% NaN post-fix vs. 9-91% pre-fix across SPY/QQQ/NVDA).

**Caveat:** for any caller that already fed uniform 1-minute data end-to-end
(no mismatch to begin with — e.g. `backtester_1min_entry.py`), this changes
RVOL from "compare this exact minute to history's same exact minute" to
"compare cumulative bucket volume to history's bucket average." Re-running
old backtest audits may show slightly different numbers than before, not
because anything is wrong, but because the granularity changed.

### 2. ADX read up to ~14x too high (HIGH — fixed)

**Where:** `trading/mtf_features.py::compute_adx()`

**What was wrong:** the shared `wilder_smooth()` helper returns a smoothed
*sum*, not an average. That's fine for the internal +DI/-DI calculation
(`pdi`/`mdi`), because both numerator and denominator carry the same scale-up
and it cancels in the ratio. But the function reused the same helper for the
*final* DX→ADX smoothing step and returned that value directly, with no
ratio to cancel the scale-up. Proven algebraically (`sum[i] = period *
avg[i]` holds at every step of the recursion, not just asymptotically) and
confirmed with a synthetic DX series: the buggy code produced ~643 for data
whose true average was ~49.

**Impact:** confirmed live — the AI decision-support layer vetoed a real
QQQ/IFVG signal on 2026-07-28 citing "ADX at 676.94 is impossible."
676.94/14 ≈ 48, a plausible real value. Three consumers share this function:
`trading/entry.py`'s AI decision-support feature snapshot (confirmed
affected), `backtest_exit_sim.py`'s trend-death check (affected — see the
correction below), and `trading/position_manager.py`'s exit logic.

**Correction to an earlier claim in this session:** I initially said this
"silently weakened position_manager.py's ADX<20 exit condition on every open
position." That overstates it. The live exit path defaults to
`simplified_exit_live.py` (`simplified_exit_mode: True` in `config.py`),
which only checks a hard stop, a 3.0x-ATR chandelier trail, and a time cap —
it never reads ADX at all. The ADX-gated "VWAP breach + trend breakdown"
condition only exists in the fallback 9-condition engine
(`risk.should_exit()`), which runs only if simplified mode is off or bar
data isn't ready. So the real, confirmed live-exit impact is conditional,
not universal. It did, however, affect `backtest_exit_sim.py` — meaning the
earlier A/B test that justified switching to the simplified engine
(`ab_test_exit_complexity.py`) ran the 9-condition engine with one of its
nine conditions barely able to fire. That doesn't necessarily change the
conclusion (the simplified engine may still be better), but it's a real
caveat on the evidence behind that decision. Not recommending a re-run right
now — flagging it so it's known.

**Fix:** divide the final smoothed DX value by `period` before returning it.
One line, in the shared function, so all three consumers get the same fix
automatically (no divergence risk).

## New findings from this pass

### 3. Dead code with a latent reindex bug (LOW — not fixed, recommend removing)

**Where:** `signals.py::detect_orb_breakout()`

`rvol_series.reindex(today_df.index)` reindexes against `today_df`'s index
*after* it was built with `.reset_index(drop=True)` — the same class of
misalignment bug that was already found and fixed in
`strategy_router.py::_build_indicator_frame()` and
`trading/diagnostics.py::_log_bar_thinking()` earlier in this project. This
instance is real, but the function is dead code: it's imported into
`trading/entry.py` but never actually called anywhere. The live ORB
strategy runs through `strategies/inst_orb.py` instead. Its docstring
("called once per tick by trading_logic._tick()") is stale and refers to a
module name that no longer exists in the codebase.

**Recommendation:** either delete `detect_orb_breakout()` and its now-unused
import, or fix the reindex and update the docstring if there's a reason to
keep it around. Zero live impact either way.

### 4. RVOL threshold floor has a one-minute boundary gap (LOW — not fixed)

**Where:** `strategies/base.py::_get_dynamic_rvol_threshold()`

The "mid-day bleed" relaxation (`10:30 <= bar_min <= 13:00` → threshold
0.75x) uses an inclusive `<=` at the 10:30 boundary. The floor applied right
after it (`floor = 0.75 if bar_min > 10:30 else 1.0`) uses a strict `>` at
the same boundary. At exactly bar_min == 10:30, the relaxed threshold
computes to 0.75 but then gets overridden back to 1.0 by
`max(threshold, floor)`, since the floor's strict comparison doesn't
consider 10:30 itself "past" the boundary. Affects one single minute of the
session. Fix would be changing the floor's comparison to `>=` to match the
mid_day window's own boundary, if it's worth the risk of a one-line change
for a one-minute edge case.

### 5. INST_ORB confidence formula doesn't match its own docstring (LOW — not fixed)

**Where:** `strategies/inst_orb.py::_compute_confidence()`

The docstring describes five additive weighted components (35% RVOL + 25%
proximity + 20% trend + 10% flip penalty + 10% retest bonus = 100%). The
actual code applies `flip_multiplier` as a *multiplicative* haircut (0.85x)
to the entire score, not as its own additive 10% component. The formula
still produces a bounded, sane score (verified: max 1.00, min ~0.22-0.26),
so this isn't a functional bug — but the docstring would mislead anyone
tuning these weights later without reading the code first. Also: `is_retest`
is hardcoded `True` at the only live call site, so the `is_retest=False`
branch (2.0-ATR proximity scale) is unreachable dead code, not a bug, just
worth knowing before "fixing" something that never runs.

## Areas checked and confirmed correct

- **VWAP / VWAP bands** (`signals.py`) — standard cumulative typical-price
  formula, correctly resets daily, correct zero-division guards. No issues.
- **ATR** (`signals.py`, `position_manager.py`, `strategy_router.py`) —
  standard true-range + EWM smoothing, consistent across all three
  implementations. No issues.
- **Every other `.reindex()` call in the codebase** — swept all 5 occurrences
  outside the two known-fixed ones and the one dead-code instance above;
  `backtester_1min_entry.py` and `backtester.py`'s ADX reindex are both
  correctly implemented (label-based lookups against matching indices, not
  positional after a reset). No further instances of the misalignment bug.
- **`router_gates.py` pipeline order and gate stacking** — order matches its
  own documentation comment; confidence adjustments (confluence bonus, VWAP
  weight, session bias, MTF boost) are bounded and don't have an obvious
  compounding-past-100% issue.
- **`risk.py::calculate_contracts()`** — position sizing formula matches its
  docstring exactly, tier logic and notional caps check out.
- **`risk.py::evaluate_rr()`** — R:R math (slippage-adjusted entry/target/stop,
  net reward over net risk) matches its docstring exactly.
- **`simplified_exit_live.py`** (the actual default live exit engine) —
  three rules (hard stop, chandelier trail, time cap), all straightforward,
  no bugs found.
- **`regime_manager.py::compute_adx_series()`** — a *separate*, correct ADX
  implementation using pandas EWM (a true average). This is why regime-gate
  ADX readings in the logs looked sane (e.g. "ADX 21 < 25") while the other,
  buggy implementation was producing nonsense. Confirms these are genuinely
  two independent implementations, not shared code — worth unifying at some
  point so this can't happen again, but out of scope to do right now.

## Open questions I couldn't resolve from code + logs alone

- **Why did RVOL decay gradually (Jul 19-22 fine → Jul 23 partial → Jul 28
  dead) if the buggy code path has been unchanged since before Jul 22?** I
  don't have a confirmed answer. The mechanism is proven broken right now
  regardless of when it started; I didn't want to invent a clean timeline I
  can't back up with evidence.
- **`position_manager.py` and `trading/entry.py` are 1,351 and ~1,700+ lines
  respectively** — both far past this project's own 200-line-per-file
  guideline. Not a bug, but worth flagging: files this size make future
  audits like this one slower and riskier. Splitting them is a real project,
  not something to do as a drive-by.

## Coverage note

Deep, line-by-line review: `signals.py`, `strategies/base.py`,
`strategies/inst_orb.py`, `trading/mtf_features.py`,
`trading/position_manager.py`, `trading/simplified_exit_live.py`, the
`.reindex()`/`.reset_index()` call sites across the whole repo, and the
core sizing/R:R functions in `risk.py`.

Lighter pass (imports, call sites, targeted grep, not full line-by-line):
`router_gates.py`, `strategy_router.py`, `trading/entry.py`,
`backtester.py`, `backtest_exit_sim.py`, `config.py`.

Not covered this pass: `strategies/vwap_pb.py` (reviewed earlier this
project, not re-audited today), `fvg.py`, `ifvg.py`, `bos_mss.py`,
`trend_cont.py`, `aft_rev.py`, `chan_break.py`, `gap_go.py`, `mid_brk.py`
(disabled), `database.py`, `api/routes/*.py`, `scanner.py` beyond the one
section read earlier this session, and the frontend. If you want those
covered too, say the word and I'll keep going — flagging the boundary now
rather than implying this was exhaustive when it wasn't.
