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

## Still fixed or outside this panel

These are genuine remaining configuration boundaries, not claims that all controls are finished:

| Area | What remains fixed | Assessment |
| --- | --- | --- |
| Strategy candle intervals | Entry intervals in adapters/catalog, and native structural-exit intervals. The configurable candle interval is specifically the partial-profit fail-safe. | A reasonable future control, but changing it requires coordinated warmup, signal timestamps, exit sampling and evidence. It is not connected as a general timeframe selector. |
| Opening-Range Pullback | First one-minute opening range, calls-only native route, opposite range edge as structural reference, 2R reference target, first-retouch/rearm mechanics. | Range length and target multiple are potential user parameters. Direction and trigger algorithm are still strategy rules. |
| Native Afternoon FVG | Structural stop at the more conservative trigger extreme or one ATR away; 2R reference target; first-retest and midpoint confirmation logic. | ATR stop multiple and target multiple remain potential configurable parameters. |
| Failed-Range | Opening-range window and VWAP target choice; failure/rearm sequence. Buffer and breakout/failure deadlines are editable. | Range window could be exposed; target method is still the defined strategy. |
| Context ORB variants | 15-minute opening range, 9:45 to 11:00 entry window, 20-bar volume comparison; native partial sale still uses half the contracts. | These remain configuration gaps. The configurable first-sale percentage applies to the assigned partial-profit policy, not this separate native context exit. |
| Context VWAP | Five-minute trigger, previous-high target, five-minute VWAP breach exit, fixed 10:30 displacement checkpoint. | The panel exposes EMA/displacement or efficiency inputs, not these timing/target rules. |
| Squeeze | Hourly trigger/exit cadence and calls-only behavior. | Indicator periods and premium target are editable; timeframe/direction are not. |
| Library strategies | Numeric/bool/time dataclass inputs are exposed; structural algorithms, allowed sides, resampling and replay emission policy remain code. | The nullable ORB RSI/MACD active_date field is omitted. It is a single-date replay restriction, not an appropriate everyday trading default. |
| Contract target ranking | “Cost $150 to $250, closest to $200” retains that exact ranking band even if broader eligibility filters are edited. | This is explicitly named. A custom target price/range is not yet a panel control. |
| Entry gates | Account/router gates, premarket filters and trading permissions are separate from the ticker's engine parameters. | A saved chart configuration does not bypass them. |
| Account protections | Daily loss limits, buying power, mandatory session liquidation, stale/crossed quote rejection, duplicate-order controls and broker recovery. | Intentionally not weakenable through ticker configuration. |
| Other profit policies | The editable partial-profit controls require an already-assigned paper partial-profit policy. The panel does not assign an arbitrary new exit or promote one to live. | Deliberate activation boundary. |
| Warmup | Requested lookbacks still require available history; increasing an input does not manufacture data. | Very large lookbacks may leave a strategy waiting for history. |

No fixed rule above was changed by this audit. Current settings and policy assignments must remain byte-for-byte unchanged through deployment.

## Registered route inventory

A route is an implementation/version identity, not a new customer-facing strategy family. Tickers remain children of the shared strategy. All entries below passed save/reload testing with their displayed defaults in isolated settings.

| Route | Source/adapter | Exposed entry fields |
| --- | --- | --- |
| `V2_TREND_CONT` | Native | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk |
| `V2_ORB_PULLBACK` | Native | retouch_tolerance_pct, entry_deadline |
| `V2_SPY_TREND_CONT` | Native | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk |
| `V2_SPY_AFTERNOON_FVG` | Native | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, start, end |
| `V2_FAILED_OR_BREAK_VWAP_REVERSION` | Native | breakout_deadline, failure_deadline, minimum_excursion_range, minimum_vwap_room_range, stop_buffer_range |
| `V2_TSLA_TWO_LEG_TREND_PULLBACK` | Native | reference_time, entry_start, entry_end, fast_ema, slow_ema, atr_bars, impulse_atr, pullback_min_atr, pullback_max_atr, pullback_limit_bars, reward_risk |
| `CTX_ORB_NR7_OR_INSIDE` | Native | volume_ratio_minimum, narrow_range_days |
| `CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG` | Native | volume_ratio_minimum, daily_atr_period |
| `CTX_VWAP_PULLBACK_KER10_LONG` | Native | reclaim_ema_period, efficiency_period, efficiency_minimum |
| `CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG` | Native | reclaim_ema_period, displacement_fraction |
| `CTX_1H_SQUEEZE_MACD_LONG` | Native | macd_fast, macd_slow, macd_signal, band_period, band_deviations, channel_atr_multiple |
| `V2_VWAP_PULLBACK` | V2_VWAP_PULLBACK / library | fast_ema, slow_ema, atr_bars, slope_bars, touch_tolerance_pct, stop_atr_multiple, reward_risk |
| `RESEARCH_QQQ_TREND_V2` | V2_SPY_TREND_CONT / library | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk |
| `V2_AFTERNOON_COMPRESSION_BREAKOUT` | V2_AFTERNOON_COMPRESSION_BREAKOUT / library | fast_ema, slow_ema, atr_bars, compression_start, compression_end, entry_end, min_compression_bars, max_compression_pct, stop_atr_multiple, reward_risk |
| `V2_GAP_FILL_RTH` | V2_GAP_FILL_RTH / library | min_gap_pct, atr_bars, atr_trail_multiple, entry_start, entry_end |
| `V2_AFTERNOON_REVERSAL` | V2_AFTERNOON_REVERSAL / library | pivot_lookback, atr_bars, min_morning_move_pct, stop_atr_multiple, reward_risk, start_time, end_time |
| `V2_SPY_ORB_RSI_MACD_SHORT` | V2_SPY_ORB_RSI_MACD_SHORT / library | min_range_pct, max_range_pct, entry_deadline, rsi_period, rsi_ceiling, macd_fast, macd_slow |
| `V2_IMPULSE_ANCHORED_VWAP_PULLBACK` | V2_IMPULSE_ANCHORED_VWAP_PULLBACK / library | channel_bars, atr_period, impulse_range_atr, close_location_minimum, minimum_pullback_bars, maximum_pullback_bars, touch_tolerance_atr, failure_tolerance_atr, stop_buffer_atr, target_r, entry_start, entry_end |
| `RESEARCH_CTX_ORB_ATR10_V2` | CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG / library | volume_ratio_minimum, daily_atr_period |
| `RESEARCH_FAILED_RANGE_V2` | V2_FAILED_OR_BREAK_VWAP_REVERSION / library | breakout_deadline, failure_deadline, minimum_excursion_range, minimum_vwap_room_range, stop_buffer_range |
| `APPROVED_V2_EMA_PULLBACK_RTH` | V2_EMA_PULLBACK_RTH / library | pullback_ema, pullback_limit_ema, trend_ema, minimum_risk_pct, target_risk_ratio, entry_start, entry_end |
| `APPROVED_V2_FAIR_VALUE_GAP` | V2_FAIR_VALUE_GAP / library | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, stop_atr_multiple, reward_risk |
| `APPROVED_V2_MIDDAY_BREAKDOWN` | V2_MIDDAY_BREAKDOWN / library | base_start, base_end, entry_start, entry_end, atr_bars, max_base_atr_multiple, stop_atr_multiple, reward_risk |
| `APPROVED_V2_OPENING_MOMENTUM_RTH_EXPLORATORY` | V2_OPENING_MOMENTUM_RTH_EXPLORATORY / library | opening_bars, min_move_pct, atr_bars, atr_trail_multiple |
| `APPROVED_V2_ORB_CONFIRMED_BREAKOUT` | V2_ORB_CONFIRMED_BREAKOUT / library | min_range_pct, max_range_pct, breakout_buffer_pct, entry_deadline, stop_range_fraction, reward_risk, allow_long, allow_short |
| `APPROVED_V2_RANGE_SWEEP_RECLAIM` | V2_RANGE_SWEEP_RECLAIM / library | range_bars, atr_bars, maximum_efficiency, minimum_sweep_atr, minimum_vwap_room_atr, stop_atr, minimum_reward_risk, rearm_distance_atr, entry_start, entry_end |
| `APPROVED_V2_TURTLE_SOUP_RTH` | V2_TURTLE_SOUP_RTH / library | lookback_bars, target_risk_ratio, entry_start, entry_end |
| `APPROVED_V2_VWAP_REVERSION_RTH` | V2_VWAP_REVERSION_RTH / library | atr_bars, ema_bars, band_atr, stop_atr, entry_start, entry_end |
| `APPROVED_TV_SUPERTREND_REVERSAL_V4` | TV_SUPERTREND_REVERSAL_V4 / library | atr_period, multiplier, use_rma_atr |
| `APPROVED_V2_VWAP_PULLBACK` | V2_VWAP_PULLBACK / library | fast_ema, slow_ema, atr_bars, slope_bars, touch_tolerance_pct, stop_atr_multiple, reward_risk |
| `APPROVED_V2_TREND_CONT` | V2_TREND_CONT / library | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk |
| `APPROVED_V2_SPY_TREND_CONT` | V2_SPY_TREND_CONT / native_trend | fast_ema, slow_ema, breakout_bars, atr_bars, stop_atr_multiple, reward_risk |
| `APPROVED_V2_SPY_AFTERNOON_FVG` | V2_SPY_AFTERNOON_FVG / native_fvg | fast_ema, slow_ema, atr_bars, scan_bars, min_gap_atr, start, end |
| `APPROVED_CTX_ORB_NR7_OR_INSIDE` | CTX_ORB_NR7_OR_INSIDE / context | volume_ratio_minimum, narrow_range_days |
| `APPROVED_CTX_VWAP_PULLBACK_KER10_LONG` | CTX_VWAP_PULLBACK_KER10_LONG / context | reclaim_ema_period, efficiency_period, efficiency_minimum |
| `APPROVED_CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG` | CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG / context | reclaim_ema_period, displacement_fraction |
| `APPROVED_CTX_1H_SQUEEZE_MACD_LONG` | CTX_1H_SQUEEZE_MACD_LONG / squeeze | macd_fast, macd_slow, macd_signal, band_period, band_deviations, channel_atr_multiple |
| `APPROVED_V2_ORB_PULLBACK` | V2_ORB_PULLBACK / retouch | retouch_tolerance_pct, entry_deadline |
| `APPROVED_V2_TSLA_TWO_LEG_TREND_PULLBACK` | V2_TSLA_TWO_LEG_TREND_PULLBACK / two_leg | reference_time, entry_start, entry_end, fast_ema, slow_ema, atr_bars, impulse_atr, pullback_min_atr, pullback_max_atr, pullback_limit_bars, reward_risk |

## Verification and limitations

- Cross-registry tests save/reload all 39 routes, prove no mutation of unrelated dictionary settings, and check all displayed entry values reach the scoped parameter reader.
- Targeted tests exercise native/library configuration, contract selection, timer execution versus displayed values, frozen old-position behavior, paper/live/account isolation, partial fills, restarts, duplicate orders, and custom fail-safe candle intervals.
- Frontend tests exercise timer/ranking precedence, clearing timers and replacement-policy suppression.
- Production verification is read-only. A live broker order is not needed or authorized to verify this configuration repair.
- Offline execution tests are not actual market-session execution evidence.

Rollback: retain readers and management for any entry-frozen custom policy. Revert configuration-writing/UI changes through deploy.sh if necessary, preserving settings, account switches, history and existing positions. Never restore settings from an older snapshot merely to roll back this display/validation repair.
