# Entry research-source guard: Prompt 2.3 and 2.4

This release adds a live-entry prerequisite only. Paper entries, exits, account risk,
strategy switches and live enablement are unchanged. This guard never grants permission.

## Rules and defaults

- Existing `paper_trading` defaults to true. Paper bypasses this guard.
- Existing `alpaca_data_plan` defaults to free. An explicitly consolidated or OPRA
  evidence source requires the exact value premium for live entries.
- Unknown current-version sources refuse live entries even with premium.
- No new settings, override switch, threshold or subscription purchase.
- Evidence is cached per process/release; restart through deployment after approved
  evidence corrections. Missing, malformed or wrong-version evidence is unknown.
- Checks run after signal selection and again with fresh settings immediately before
  the normal automated entry submission. Refusal reason code is
  `research_data_parity`, with readable detail in the existing evaluation/journal log.
- Exit and position-recovery paths are not blocked by this new-entry check.

## Source inventory

Only the current catalog artifact's explicit market_data.source counts. An older
version or a report filename is not proof of the current version's data source.
All rows below have an **unverified underlying feed**. OPRA describes option quotes,
not consolidated stock candles. Failed-Range's separate long-history source names
Alpaca stock bars but does not say IEX or SIP. No historical evidence was rewritten.

| Strategy | ID | Version | Explicit primary source | Evidence file |
| --- | --- | --- | --- | --- |
| Trend Continuation | V2_TREND_CONT | research.1 | unknown | config/strategy_evidence/v2_trend_cont-research.1.json |
| TSLA Opening-Range Pullback | V2_ORB_PULLBACK | 2.0.0 | paid Databento OPRA CBBO-1m archive | config/strategy_evidence/v2_orb_pullback-2.0.0.json |
| SPY Trend Continuation | V2_SPY_TREND_CONT | 2.1.0 | paid Databento OPRA CBBO-1m archive | config/strategy_evidence/v2_spy_trend_cont-2.1.0.json |
| SPY Afternoon Fair Value Gap | V2_SPY_AFTERNOON_FVG | 2.1.0 | paid Databento OPRA CBBO-1m archive | config/strategy_evidence/v2_spy_afternoon_fvg-2.1.0.json |
| SPY Failed-Range Recovery | V2_FAILED_OR_BREAK_VWAP_REVERSION | 2.1.0 | paid Databento OPRA CBBO-1m archive | config/strategy_evidence/v2_spy_failed_range_recovery-2.1.0.json |
| TSLA Two-Leg Trend Pullback | V2_TSLA_TWO_LEG_TREND_PULLBACK | 2.2.0 | unknown | config/strategy_evidence/v2_tsla_two_leg_trend_pullback-2.2.0.json |
| Context-Filtered ORB (NR7 / Inside Day) | CTX_ORB_NR7_OR_INSIDE | 0.1.0 | paid Databento OPRA CBBO-1m archives | config/strategy_evidence/ctx_orb_nr7_inside-0.1.0.json |
| Context-Filtered ORB (ATR10) | CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG | 0.1.0 | paid Databento OPRA CBBO-1m archives | config/strategy_evidence/ctx_orb_atr10-0.1.0.json |
| VWAP Pullback (1-Hour KER) | CTX_VWAP_PULLBACK_KER10_LONG | 0.1.0 | paid Databento OPRA CBBO-1m archives | config/strategy_evidence/ctx_vwap_ker-0.1.0.json |
| VWAP Pullback (10:30 Displacement) | CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG | 0.2.0 | paid Databento OPRA CBBO-1m archives | config/strategy_evidence/ctx_vwap_displacement-0.2.0.json |
| 1-Hour Bollinger / Keltner Squeeze | CTX_1H_SQUEEZE_MACD_LONG | 0.1.0 | paid Databento OPRA CBBO-1m archives | config/strategy_evidence/ctx_squeeze_macd-0.1.0.json |
| VWAP Pullback | V2_VWAP_PULLBACK | research.1 | unknown | config/strategy_evidence/v2_vwap_pullback-orders.json |
| Trend Continuation | RESEARCH_QQQ_TREND_V2 | 2.1.0 | unknown | config/strategy_evidence/research_qqq_trend_v2-orders.json |
| Afternoon Compression Breakout | V2_AFTERNOON_COMPRESSION_BREAKOUT | research.2 | unknown | config/strategy_evidence/v2_afternoon_compression_breakout-orders.json |
| Gap Fill | V2_GAP_FILL_RTH | research.2 | unknown | config/strategy_evidence/v2_gap_fill_rth-orders.json |
| Afternoon Reversal | V2_AFTERNOON_REVERSAL | research.1 | unknown | config/strategy_evidence/v2_afternoon_reversal-orders.json |
| ORB RSI/MACD Short | V2_SPY_ORB_RSI_MACD_SHORT | research.2 | unknown | config/strategy_evidence/v2_spy_orb_rsi_macd_short-orders.json |
| Impulse Anchored VWAP Pullback | V2_IMPULSE_ANCHORED_VWAP_PULLBACK | research.2 | unknown | config/strategy_evidence/v2_impulse_anchored_vwap_pullback-orders.json |
| Context-Filtered ORB (ATR10) | RESEARCH_CTX_ORB_ATR10_V2 | 0.1.0.research.2 | unknown | config/strategy_evidence/research_ctx_orb_atr10_v2-orders.json |
| Failed-Range Recovery | RESEARCH_FAILED_RANGE_V2 | 2.1.0.research.2 | unknown | config/strategy_evidence/research_failed_range_v2-orders.json |

## Limits and unresolved parity

This implements the audit's requested plan-level rule, not full data-feed parity.
Premium is NOT sufficient proof: broker/alpaca_bars.py still has IEX fallbacks and
IEX history/snapshot paths. OPRA option evidence does not identify stock-bar input.
Tradier evidence for other cohorts does not validate the current artifact. The plan
prerequisite has no provider bypass, as requested; it is not a statement that Tradier
needs an Alpaca subscription. Do not enable live based on this check passing.
Actual source provenance across signal timeframes needs a separate reviewed change.

## Verification and rollback

Nine focused tests cover paper bypass, unknown source, consolidated/free refusal,
premium prerequisite, explicit IEX classification, no predecessor inference, malformed
or missing evidence, version mismatch, account isolation and final submission refusal.
The final-boundary test executes the real guard block and confirms no submission.
Full production suite is required by deploy.sh. No orders are used for smoke tests.

Rollback if paper regressions, runtime integrity errors or health failures appear:
revert only this release's entry hooks, guard, tests/docs and runtime-review selection
through deploy.sh to the prior 9024842 behavior. No database migration or setting
restoration is needed. Do not delete historical evidence or change open-position exits.

Prompt 2.4 covers the implemented 2.3 paths here. Prompt 2.1's cost hurdle and 2.2's
shared spread cap remain unimplemented and are not represented as tested or complete.
