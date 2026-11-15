# Strategy configuration audit, November 14, 2026

Scope: Settings > Strategies > ticker > Configure, all 39 registered execution routes. Audit covers the panel, API save validation, account/mode/version scope, entry parameter readers, contract selection, frozen exit controls, and existing-position isolation. It does not claim that every number in every strategy algorithm is a user-editable parameter.

## Confirmed defects repaired

1. QQQ Trend Continuation and the research Failed-Range alias were incorrectly sent to a library factory that does not exist for those aliases. Valid configuration saves could fail with an internal error. Validation now follows their actual native engine.
2. A selected timer could disappear from the displayed effective values after another native exit parameter was saved. Execution still used the timer. Display now applies the same field-level precedence as execution: explicit frozen holding minutes, then selected timer, then native default.
3. The panel offered a numeric timer and a second timer dropdown. Editing one, then another native parameter, could reintroduce the old value. There is now one minutes field. Structural strategies have an explicit custom-time-limit switch; parameters displaced by that timer are hidden.
4. ORB retouch tolerance accepted values that its engine rejects. Saving now enforces the engine's existing less-than-1% constraint. The existing default is unchanged.

Contract ranking was checked separately. Explicit contract controls take priority over an older Research contract selection. The panel keeps the displayed selected ranking when another contract filter is edited. This precedence is now covered by frontend tests. No contract ranking was changed in any account.

## What is editable and connected

- Each route's declared entry inputs listed below.
- Per-ticker position-risk percentage and maximum position-cost percentage, subject to existing account safety limits.
- Expiration range, option-price range, bid/ask spread, open interest, dollar spread and contract ranking.
- Applicable native time caps, bar caps and native premium thresholds.
- Existing assigned paper partial-profit policy: activation gain, percentage sold, profit giveback, fail-safe on/off, candle interval, candle count and option loss threshold.

Saving targets one account, mode, strategy, ticker and version. A stale revision or changed account/mode is rejected. New entries receive their saved exit configuration. Previously opened positions retain their entry-time configuration. Opening a panel performs no save.

## Remaining settings connected in this release

- Entry candle intervals, native structural-exit intervals and opening range length. ORB's unchanged default is a 15-minute opening range built from completed one-minute candles.
- Native ORB target multiple, stop range fraction, retouch minimum and supported direction gates.
- Native FVG stop ATR multiple, target multiple, first-retest and midpoint-close requirements.
- Two-Leg stop ATR multiple and directional-confirmation requirement.
- Failed-Range VWAP target fraction; context entry windows, volume lookback, midpoint fraction, VWAP history/checkpoint and higher-timeframe interval.
- Native context partial-sale percentage, native bar holding caps and target-premium contract ranking bounds/preferred price.
- Nullable date restriction can be cleared rather than being permanently read-only.

Custom candle intervals require complete source observations. Missing minutes do not create a completed candle. Configured entry reference times must align with the chosen interval. Old trades retain their frozen settings and old reviewed seed compatibility. Replacement profit policies continue to suppress displaced native timers.

Boundaries: mandatory account safety, session liquidation, quote-validity checks and order reconciliation are not per-ticker bypass controls. Strategy identity and its signal sequence are algorithms, not arbitrary settings. One-sided strategies do not offer a fake opposite-direction switch. Existing terminal setup sequences remain terminal; configuration changes apply to future setups. Increased lookbacks require sufficient available history. Live policy activation still follows its existing authorization rules.

## Registered route inventory

A route is an implementation/version identity, not a new customer-facing strategy family. Tickers remain children of the shared strategy. All entries below passed save/reload testing with their displayed defaults in isolated settings.

| Route | Source/adapter | Exposed entry fields |
| --- | --- | --- |
| `V2_TREND_CONT` | Native | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `V2_ORB_PULLBACK` | Native | retouch_tolerance_pct, entry_deadline, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, reward_risk, stop_range_fraction, minimum_retouch_dollars |
| `V2_SPY_TREND_CONT` | Native | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `V2_SPY_AFTERNOON_FVG` | Native | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, start, end, entry_timeframe_minutes, allow_long, allow_short, stop_atr_multiple, reward_risk, require_first_retest, require_midpoint_close |
| `V2_FAILED_OR_BREAK_VWAP_REVERSION` | Native | breakout_deadline, failure_deadline, minimum_excursion_range, minimum_vwap_room_range, stop_buffer_range, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, vwap_target_fraction |
| `V2_TSLA_TWO_LEG_TREND_PULLBACK` | Native | reference_time, entry_start, entry_end, fast_ema, slow_ema, atr_bars, impulse_atr, pullback_min_atr, pullback_max_atr, pullback_limit_bars, reward_risk, entry_timeframe_minutes, allow_long, allow_short, stop_atr_multiple, require_directional_confirmation |
| `CTX_ORB_NR7_OR_INSIDE` | Native | volume_ratio_minimum, narrow_range_days, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, entry_start, entry_end, volume_lookback_bars, midpoint_fraction |
| `CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG` | Native | volume_ratio_minimum, daily_atr_period, entry_timeframe_minutes, opening_range_minutes, entry_start, entry_end, volume_lookback_bars, midpoint_fraction |
| `CTX_VWAP_PULLBACK_KER10_LONG` | Native | reclaim_ema_period, efficiency_period, efficiency_minimum, entry_timeframe_minutes, entry_start, entry_end, context_timeframe_minutes, prior_extreme_lookback_bars |
| `CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG` | Native | reclaim_ema_period, displacement_fraction, entry_timeframe_minutes, entry_start, entry_end, displacement_checkpoint, prior_extreme_lookback_bars |
| `CTX_1H_SQUEEZE_MACD_LONG` | Native | macd_fast, macd_slow, macd_signal, band_period, band_deviations, channel_atr_multiple, entry_timeframe_minutes |
| `V2_VWAP_PULLBACK` | V2_VWAP_PULLBACK / library | fast_ema, slow_ema, atr_bars, slope_bars, touch_tolerance_pct, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `RESEARCH_QQQ_TREND_V2` | V2_SPY_TREND_CONT / library | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `V2_AFTERNOON_COMPRESSION_BREAKOUT` | V2_AFTERNOON_COMPRESSION_BREAKOUT / library | fast_ema, slow_ema, atr_bars, compression_start, compression_end, entry_end, min_compression_bars, max_compression_pct, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `V2_GAP_FILL_RTH` | V2_GAP_FILL_RTH / library | min_gap_pct, atr_bars, atr_trail_multiple, entry_start, entry_end, entry_timeframe_minutes, allow_long, allow_short |
| `V2_AFTERNOON_REVERSAL` | V2_AFTERNOON_REVERSAL / library | pivot_lookback, atr_bars, min_morning_move_pct, stop_atr_multiple, reward_risk, start_time, end_time, entry_timeframe_minutes, allow_long, allow_short |
| `V2_SPY_ORB_RSI_MACD_SHORT` | V2_SPY_ORB_RSI_MACD_SHORT / library | min_range_pct, max_range_pct, entry_deadline, rsi_period, rsi_ceiling, macd_fast, macd_slow, active_date, entry_timeframe_minutes |
| `V2_IMPULSE_ANCHORED_VWAP_PULLBACK` | V2_IMPULSE_ANCHORED_VWAP_PULLBACK / library | channel_bars, atr_period, impulse_range_atr, close_location_minimum, minimum_pullback_bars, maximum_pullback_bars, touch_tolerance_atr, failure_tolerance_atr, stop_buffer_atr, target_r, entry_start, entry_end, entry_timeframe_minutes, allow_long, allow_short |
| `RESEARCH_CTX_ORB_ATR10_V2` | CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG / library | volume_ratio_minimum, daily_atr_period, entry_timeframe_minutes, opening_range_minutes, entry_start, entry_end, volume_lookback_bars, midpoint_fraction |
| `RESEARCH_FAILED_RANGE_V2` | V2_FAILED_OR_BREAK_VWAP_REVERSION / library | breakout_deadline, failure_deadline, minimum_excursion_range, minimum_vwap_room_range, stop_buffer_range, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, vwap_target_fraction |
| `APPROVED_V2_EMA_PULLBACK_RTH` | V2_EMA_PULLBACK_RTH / library | pullback_ema, pullback_limit_ema, trend_ema, minimum_risk_pct, target_risk_ratio, entry_start, entry_end, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_FAIR_VALUE_GAP` | V2_FAIR_VALUE_GAP / library | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_MIDDAY_BREAKDOWN` | V2_MIDDAY_BREAKDOWN / library | base_start, base_end, entry_start, entry_end, atr_bars, max_base_atr_multiple, stop_atr_multiple, reward_risk, entry_timeframe_minutes |
| `APPROVED_V2_OPENING_MOMENTUM_RTH_EXPLORATORY` | V2_OPENING_MOMENTUM_RTH_EXPLORATORY / library | opening_bars, min_move_pct, atr_bars, atr_trail_multiple, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_ORB_CONFIRMED_BREAKOUT` | V2_ORB_CONFIRMED_BREAKOUT / library | min_range_pct, max_range_pct, breakout_buffer_pct, entry_deadline, stop_range_fraction, reward_risk, allow_long, allow_short, entry_timeframe_minutes |
| `APPROVED_V2_RANGE_SWEEP_RECLAIM` | V2_RANGE_SWEEP_RECLAIM / library | range_bars, atr_bars, maximum_efficiency, minimum_sweep_atr, minimum_vwap_room_atr, stop_atr, minimum_reward_risk, rearm_distance_atr, entry_start, entry_end, entry_timeframe_minutes |
| `APPROVED_V2_TURTLE_SOUP_RTH` | V2_TURTLE_SOUP_RTH / library | lookback_bars, target_risk_ratio, entry_start, entry_end, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_VWAP_REVERSION_RTH` | V2_VWAP_REVERSION_RTH / library | atr_bars, ema_bars, band_atr, stop_atr, entry_start, entry_end, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_TV_SUPERTREND_REVERSAL_V4` | TV_SUPERTREND_REVERSAL_V4 / library | atr_period, multiplier, use_rma_atr, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_VWAP_PULLBACK` | V2_VWAP_PULLBACK / library | fast_ema, slow_ema, atr_bars, slope_bars, touch_tolerance_pct, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_TREND_CONT` | V2_TREND_CONT / library | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_SPY_TREND_CONT` | V2_SPY_TREND_CONT / native_trend | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk, entry_timeframe_minutes, allow_long, allow_short |
| `APPROVED_V2_SPY_AFTERNOON_FVG` | V2_SPY_AFTERNOON_FVG / native_fvg | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, start, end, entry_timeframe_minutes, allow_long, allow_short, stop_atr_multiple, reward_risk, require_first_retest, require_midpoint_close |
| `APPROVED_CTX_ORB_NR7_OR_INSIDE` | CTX_ORB_NR7_OR_INSIDE / context | volume_ratio_minimum, narrow_range_days, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, entry_start, entry_end, volume_lookback_bars, midpoint_fraction |
| `APPROVED_CTX_VWAP_PULLBACK_KER10_LONG` | CTX_VWAP_PULLBACK_KER10_LONG / context | reclaim_ema_period, efficiency_period, efficiency_minimum, entry_timeframe_minutes, entry_start, entry_end, context_timeframe_minutes, prior_extreme_lookback_bars |
| `APPROVED_CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG` | CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG / context | reclaim_ema_period, displacement_fraction, entry_timeframe_minutes, entry_start, entry_end, displacement_checkpoint, prior_extreme_lookback_bars |
| `APPROVED_CTX_1H_SQUEEZE_MACD_LONG` | CTX_1H_SQUEEZE_MACD_LONG / squeeze | macd_fast, macd_slow, macd_signal, band_period, band_deviations, channel_atr_multiple, entry_timeframe_minutes |
| `APPROVED_V2_ORB_PULLBACK` | V2_ORB_PULLBACK / retouch | retouch_tolerance_pct, entry_deadline, entry_timeframe_minutes, allow_long, allow_short, opening_range_minutes, reward_risk, stop_range_fraction, minimum_retouch_dollars |
| `APPROVED_V2_TSLA_TWO_LEG_TREND_PULLBACK` | V2_TSLA_TWO_LEG_TREND_PULLBACK / two_leg | reference_time, entry_start, entry_end, fast_ema, slow_ema, atr_bars, impulse_atr, pullback_min_atr, pullback_max_atr, pullback_limit_bars, reward_risk, entry_timeframe_minutes, allow_long, allow_short, stop_atr_multiple, require_directional_confirmation |

## Verification and limitations

- Cross-registry tests save/reload all 39 routes, prove no mutation of unrelated dictionary settings, and check all displayed entry values reach the scoped parameter reader.
- Targeted tests exercise native/library configuration, contract selection, timer execution versus displayed values, frozen old-position behavior, paper/live/account isolation, partial fills, restarts, duplicate orders, and custom fail-safe candle intervals.
- Frontend tests exercise timer/ranking precedence, clearing timers and replacement-policy suppression.
- Production verification is read-only. A live broker order is not needed or authorized to verify this configuration repair.
- Offline execution tests are not actual market-session execution evidence.

Rollback: retain readers and management for any entry-frozen custom policy. Revert configuration-writing/UI changes through deploy.sh if necessary, preserving settings, account switches, history and existing positions. Never restore settings from an older snapshot merely to roll back this display/validation repair.

## Added execution verification

Eleven targeted tests exercise actual changed calculations, not only parameter reads: custom ORB range/direction/stop/target, FVG stop/target, all permitted entry intervals with incomplete/missing candles, context volume/time/midpoint, target contract ranking, frozen partial-sale quantity after partial fills/restart, frozen structural close timing, nullable dates and invalid reference alignment, Two-Leg stop distance, SuperTrend close safety on custom intervals, and custom VWAP completed-bar decisions. Browser saved opening range 10 minutes and target 3R in an isolated in-memory preview only. Production account settings were not edited. Final full regression and deployment verification are recorded in CELO_CURRENT_STATUS.md.
