// Display-only explanations. Never used to set defaults or execute trades.
export const settingHelp = {
  "allow_long": {
    "label": "Allow bullish trades",
    "meaning": "Allows setups that expect the stock to rise.",
    "effect": "Off skips bullish entries for this strategy and ticker; it does not close existing positions.",
    "summary": "Allows setups that expect the stock to rise.",
    "detail": ""
  },
  "allow_short": {
    "label": "Allow bearish trades",
    "meaning": "Allows setups that expect the stock to fall.",
    "effect": "Off skips bearish entries; it does not close existing positions.",
    "summary": "Allows setups that expect the stock to fall.",
    "detail": ""
  },
  "entry_timeframe_minutes": {
    "label": "Entry candle length (minutes)",
    "meaning": "Each candle groups this many minutes of stock prices. Entry checks use completed candles.",
    "effect": "Longer candles update less often; shorter candles react sooner and include more small price moves.",
    "summary": "Each candle groups this many minutes of stock prices.",
    "detail": "Entry checks use completed candles."
  },
  "context_timeframe_minutes": {
    "label": "Trend candle length (minutes)",
    "meaning": "The larger candles used to judge the surrounding trend.",
    "effect": "Longer candles give a slower view of the trend and need more history.",
    "summary": "The larger candles used to judge the surrounding trend.",
    "detail": ""
  },
  "structural_timeframe_minutes": {
    "label": "Exit candle length (minutes)",
    "meaning": "How much time each completed candle covers for the active chart exit.",
    "effect": "Longer candles can delay confirmation of a break; shorter candles check more often.",
    "summary": "How much time each completed candle covers for the active chart exit.",
    "detail": ""
  },
  "fast_ema": {
    "label": "Fast trend average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "slow_ema": {
    "label": "Slow trend average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "pullback_ema": {
    "label": "Pullback crossing average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "pullback_limit_ema": {
    "label": "Pullback depth average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "trend_ema": {
    "label": "Main trend average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "ema_bars": {
    "label": "Price average (candles)",
    "meaning": "An EMA is an average that gives newer stock prices more weight. This is its candle count.",
    "effect": "A larger count responds more slowly; a smaller count reacts faster. This can change which setups qualify.",
    "summary": "Number of candles used in this price average.",
    "detail": "An EMA is an average that gives newer stock prices more weight. This is its candle count."
  },
  "atr_bars": {
    "label": "Typical price movement lookback (candles)",
    "meaning": "ATR measures the stock's usual movement per candle. This sets how many candles inform it.",
    "effect": "More candles smooth the estimate; fewer make it react faster. Other distances based on ATR change with it.",
    "summary": "Number of candles used to measure typical stock-price movement.",
    "detail": "ATR measures the stock's usual movement per candle. This sets how many candles inform it."
  },
  "atr_period": {
    "label": "Typical price movement lookback (candles)",
    "meaning": "ATR measures the stock's usual movement per candle. This sets how many candles inform it.",
    "effect": "More candles smooth the estimate; fewer make it react faster. Other distances based on ATR change with it.",
    "summary": "Number of candles used to measure typical stock-price movement.",
    "detail": "ATR measures the stock's usual movement per candle. This sets how many candles inform it."
  },
  "daily_atr_period": {
    "label": "Typical daily movement lookback (days)",
    "meaning": "How many daily candles are used to estimate the stock's usual daily movement.",
    "effect": "A longer history changes more slowly and can change whether the prior range qualifies.",
    "summary": "How many daily candles are used to estimate the stock's usual daily movement.",
    "detail": ""
  },
  "use_rma_atr": {
    "label": "Use Wilder smoothing for price movement",
    "meaning": "Chooses Wilder's smoothed ATR instead of the alternate average used by this strategy.",
    "effect": "Switching changes the trend band calculation and can move reversal signals.",
    "summary": "Chooses Wilder's smoothed ATR instead of the alternate average used by this strategy.",
    "detail": ""
  },
  "multiplier": {
    "label": "Trend band distance (times ATR)",
    "meaning": "Sets how far the trend bands sit from the stock price using typical movement.",
    "effect": "Larger bands generally need a bigger move to reverse the trend signal.",
    "summary": "Sets how far the trend bands sit from the stock price using typical movement.",
    "detail": ""
  },
  "entry_start": {
    "label": "Start looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "start": {
    "label": "Start looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "start_time": {
    "label": "Start looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "entry_end": {
    "label": "Stop looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "end": {
    "label": "Stop looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "end_time": {
    "label": "Stop looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "entry_deadline": {
    "label": "Stop looking for entries (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "breakout_deadline": {
    "label": "Latest allowed initial breakout (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "failure_deadline": {
    "label": "Latest allowed failed breakout (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "base_start": {
    "label": "Start measuring the base (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "base_end": {
    "label": "Finish measuring the base (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "compression_start": {
    "label": "Start measuring the tight range (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "compression_end": {
    "label": "Finish measuring the tight range (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "displacement_checkpoint": {
    "label": "Time to check distance from VWAP (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "reference_time": {
    "label": "Reference candle time (Eastern)",
    "meaning": "Uses this time on the New York market clock.",
    "effect": "Moving the time changes which candles qualify or are included in this step. It does not change market hours.",
    "summary": "Uses this time on the New York market clock.",
    "detail": ""
  },
  "active_date": {
    "label": "Only trade on this date",
    "meaning": "An optional date restriction for this strategy. Blank means no date restriction.",
    "effect": "Setting a date excludes entries on every other date.",
    "summary": "An optional date restriction for this strategy.",
    "detail": "Blank means no date restriction."
  },
  "opening_range_minutes": {
    "label": "Opening range length (minutes)",
    "meaning": "Time after the market opens used to find the opening high and low.",
    "effect": "A longer window waits longer before a breakout can qualify and changes the range levels.",
    "summary": "Time after the market opens used to find the opening high and low.",
    "detail": ""
  },
  "opening_bars": {
    "label": "Opening candles to measure",
    "meaning": "The number of opening candles measured before this momentum setup is evaluated.",
    "effect": "A larger count moves the evaluation later and changes the measured opening move.",
    "summary": "The number of opening candles measured before this momentum setup is evaluated.",
    "detail": ""
  },
  "breakout_bars": {
    "label": "Breakout lookback (candles)",
    "meaning": "How many earlier candles are checked for the recent high and low to break.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for the recent high and low to break.",
    "detail": ""
  },
  "scan_bars": {
    "label": "Gap search lookback (candles)",
    "meaning": "How many earlier candles are checked for recent candles for a price gap.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for recent candles for a price gap.",
    "detail": ""
  },
  "channel_bars": {
    "label": "Channel lookback (candles)",
    "meaning": "How many earlier candles are checked for the high and low before an impulse.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for the high and low before an impulse.",
    "detail": ""
  },
  "range_bars": {
    "label": "Range lookback (candles)",
    "meaning": "How many earlier candles are checked for the range to sweep and reclaim.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for the range to sweep and reclaim.",
    "detail": ""
  },
  "lookback_bars": {
    "label": "Prior extreme lookback (candles)",
    "meaning": "How many earlier candles are checked for the prior high and low for a reversal.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for the prior high and low for a reversal.",
    "detail": ""
  },
  "prior_extreme_lookback_bars": {
    "label": "Structural level lookback (candles)",
    "meaning": "How many earlier candles are checked for prior price extremes used for chart levels.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for prior price extremes used for chart levels.",
    "detail": ""
  },
  "volume_lookback_bars": {
    "label": "Volume comparison lookback (candles)",
    "meaning": "How many earlier candles are checked for the average volume used for comparison.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many earlier candles are checked for the average volume used for comparison.",
    "detail": ""
  },
  "pivot_lookback": {
    "label": "Swing confirmation candles",
    "meaning": "Candles on each side required to confirm a swing high or low.",
    "effect": "A larger number confirms swings later and can filter out smaller turns.",
    "summary": "Candles on each side required to confirm a swing high or low.",
    "detail": ""
  },
  "narrow_range_days": {
    "label": "Narrow-range comparison (days)",
    "meaning": "Number of daily ranges used to decide whether the previous day was unusually tight.",
    "effect": "More days make the narrow-range comparison cover a longer history.",
    "summary": "Number of daily ranges used to decide whether the previous day was unusually tight.",
    "detail": ""
  },
  "slope_bars": {
    "label": "VWAP direction lookback (candles)",
    "meaning": "Compares today's volume-weighted average price, VWAP, with its earlier value.",
    "effect": "A larger count measures direction over a longer stretch; a smaller count reacts to recent changes.",
    "summary": "Compares today's volume-weighted average price, VWAP, with its earlier value.",
    "detail": ""
  },
  "efficiency_period": {
    "label": "Trend consistency lookback (candles)",
    "meaning": "History used to compare straight-line progress with all the back-and-forth movement.",
    "effect": "More candles judge a longer trend; fewer emphasize recent movement.",
    "summary": "History used to compare straight-line progress with all the back-and-forth movement.",
    "detail": ""
  },
  "efficiency_minimum": {
    "label": "Minimum trend consistency (0 to 1)",
    "meaning": "Requires enough directional progress compared with back-and-forth movement.",
    "effect": "Higher is stricter and can allow fewer setups; lower accepts more choppy movement.",
    "summary": "Requires enough directional progress compared with back-and-forth movement.",
    "detail": ""
  },
  "maximum_efficiency": {
    "label": "Maximum trend consistency (0 to 1)",
    "meaning": "This reversal setup looks for a choppy range rather than a strong one-way trend.",
    "effect": "Lower requires more back-and-forth movement; higher accepts more directional ranges.",
    "summary": "This reversal setup looks for a choppy range rather than a strong one-way trend.",
    "detail": ""
  },
  "volume_ratio_minimum": {
    "label": "Minimum volume versus average",
    "meaning": "Required volume as a multiple of the comparison average. 1 means the same as average.",
    "effect": "Higher requires busier candles and can reject more entries.",
    "summary": "Required volume as a multiple of the comparison average.",
    "detail": "1 means the same as average."
  },
  "close_location_minimum": {
    "label": "Impulse close strength (0 to 1)",
    "meaning": "For bullish impulses, how near the candle high the close must be; bearish impulses mirror this near the low.",
    "effect": "Higher requires a stronger close near the favorable edge.",
    "summary": "For bullish impulses, how near the candle high the close must be; bearish impulses mirror this near the low.",
    "detail": ""
  },
  "impulse_atr": {
    "label": "Minimum impulse size (times ATR)",
    "meaning": "The strong move must be large enough compared with typical candle movement.",
    "effect": "Higher demands a larger impulse and can allow fewer setups.",
    "summary": "The strong move must be large enough compared with typical candle movement.",
    "detail": ""
  },
  "impulse_range_atr": {
    "label": "Minimum impulse size (times ATR)",
    "meaning": "The strong move must be large enough compared with typical candle movement.",
    "effect": "Higher demands a larger impulse and can allow fewer setups.",
    "summary": "The strong move must be large enough compared with typical candle movement.",
    "detail": ""
  },
  "pullback_min_atr": {
    "label": "Minimum pullback depth (times ATR)",
    "meaning": "Smallest allowed pullback compared with typical candle movement.",
    "effect": "Higher skips shallower pullbacks.",
    "summary": "Smallest allowed pullback compared with typical candle movement.",
    "detail": ""
  },
  "pullback_max_atr": {
    "label": "Maximum pullback depth (times ATR)",
    "meaning": "Largest allowed pullback compared with typical candle movement.",
    "effect": "Higher permits deeper pullbacks; lower rejects them sooner.",
    "summary": "Largest allowed pullback compared with typical candle movement.",
    "detail": ""
  },
  "minimum_pullback_bars": {
    "label": "Minimum pullback candles",
    "meaning": "How many completed candles the pullback must last.",
    "effect": "Higher requires a longer pullback before entry can qualify.",
    "summary": "How many completed candles the pullback must last.",
    "detail": ""
  },
  "maximum_pullback_bars": {
    "label": "Maximum pullback candles",
    "meaning": "How long the setup can keep waiting for its pullback.",
    "effect": "Higher gives the setup more time; lower abandons it sooner.",
    "summary": "How long the setup can keep waiting for its pullback.",
    "detail": ""
  },
  "pullback_limit_bars": {
    "label": "Maximum pullback candles",
    "meaning": "How long the setup can keep waiting for its pullback.",
    "effect": "Higher gives the setup more time; lower abandons it sooner.",
    "summary": "How long the setup can keep waiting for its pullback.",
    "detail": ""
  },
  "touch_tolerance_atr": {
    "label": "VWAP touch allowance (times ATR)",
    "meaning": "How close stock price must get to VWAP to count as a touch.",
    "effect": "Higher accepts touches farther from VWAP.",
    "summary": "How close stock price must get to VWAP to count as a touch.",
    "detail": ""
  },
  "failure_tolerance_atr": {
    "label": "Wrong-side VWAP allowance (times ATR)",
    "meaning": "Allowed close beyond anchored VWAP before the pullback setup fails.",
    "effect": "Higher tolerates a larger move against the setup before rejecting it.",
    "summary": "Allowed close beyond anchored VWAP before the pullback setup fails.",
    "detail": ""
  },
  "minimum_sweep_atr": {
    "label": "Minimum range overshoot (times ATR)",
    "meaning": "How far price must pass a range edge before a reclaim can qualify.",
    "effect": "Higher requires a deeper overshoot.",
    "summary": "How far price must pass a range edge before a reclaim can qualify.",
    "detail": ""
  },
  "rearm_distance_atr": {
    "label": "Distance before another setup (times ATR)",
    "meaning": "Movement needed to rearm the range-sweep setup.",
    "effect": "Higher requires a larger reset before another signal.",
    "summary": "Movement needed to rearm the range-sweep setup.",
    "detail": ""
  },
  "minimum_vwap_room_atr": {
    "label": "Minimum room toward VWAP (times ATR)",
    "meaning": "Required distance from entry toward the VWAP target.",
    "effect": "Higher rejects setups with less room to move.",
    "summary": "Required distance from entry toward the VWAP target.",
    "detail": ""
  },
  "minimum_vwap_room_range": {
    "label": "Minimum room toward VWAP (range fraction)",
    "meaning": "Required room toward VWAP compared with the opening range. 0.1 means one tenth of that range.",
    "effect": "Higher requires more room and can reject more setups.",
    "summary": "Required room toward VWAP compared with the opening range.",
    "detail": "0.1 means one tenth of that range."
  },
  "minimum_excursion_range": {
    "label": "Minimum breakout distance (range fraction)",
    "meaning": "How far price must break outside the opening range. 0.1 means one tenth of its width.",
    "effect": "Higher requires a bigger initial breakout before a failure can qualify.",
    "summary": "How far price must break outside the opening range.",
    "detail": "0.1 means one tenth of its width."
  },
  "minimum_retouch_dollars": {
    "label": "Minimum retest allowance ($ of stock price)",
    "meaning": "A dollar floor for how close a retest must come to its level. The larger of this and the percentage allowance is used.",
    "effect": "Higher can count more distant retests as touches.",
    "summary": "A dollar floor for how close a retest must come to its level.",
    "detail": "The larger of this and the percentage allowance is used."
  },
  "retouch_tolerance_pct": {
    "label": "Retest allowance (fraction)",
    "meaning": "Distance from the breakout level that still counts as a retest. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher accepts retests farther from that level.",
    "summary": "Distance from the breakout level that still counts as a retest.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "touch_tolerance_pct": {
    "label": "VWAP touch allowance (fraction)",
    "meaning": "Distance from VWAP that still counts as a touch. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher accepts touches farther from VWAP.",
    "summary": "Distance from VWAP that still counts as a touch.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "max_compression_pct": {
    "label": "Maximum tight-range width (fraction)",
    "meaning": "Largest allowed width of the compression range relative to stock price. Enter a fraction: 0.01 means 1%.",
    "effect": "Lower requires a tighter range.",
    "summary": "Largest allowed width of the compression range relative to stock price.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "min_gap_pct": {
    "label": "Minimum opening gap (fraction)",
    "meaning": "Smallest qualifying opening gap relative to stock price. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher skips smaller opening gaps.",
    "summary": "Smallest qualifying opening gap relative to stock price.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "min_morning_move_pct": {
    "label": "Minimum morning move (fraction)",
    "meaning": "Smallest morning move before looking for an afternoon reversal. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher requires a larger morning move.",
    "summary": "Smallest morning move before looking for an afternoon reversal.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "min_move_pct": {
    "label": "Minimum opening move (fraction)",
    "meaning": "Smallest opening move needed for the momentum setup. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher skips smaller moves.",
    "summary": "Smallest opening move needed for the momentum setup.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "min_range_pct": {
    "label": "Minimum opening range width (fraction)",
    "meaning": "Smallest qualifying opening range relative to stock price. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher skips narrower ranges.",
    "summary": "Smallest qualifying opening range relative to stock price.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "max_range_pct": {
    "label": "Maximum opening range width (fraction)",
    "meaning": "Largest qualifying opening range relative to stock price. Enter a fraction: 0.01 means 1%.",
    "effect": "Lower skips wider ranges.",
    "summary": "Largest qualifying opening range relative to stock price.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "breakout_buffer_pct": {
    "label": "Extra distance beyond the range (fraction)",
    "meaning": "Required move beyond the range edge before a breakout qualifies. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher waits for a bigger break.",
    "summary": "Required move beyond the range edge before a breakout qualifies.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "minimum_risk_pct": {
    "label": "Minimum entry-to-stop distance (fraction)",
    "meaning": "Smallest stock-price distance between entry and the calculated stop allowed for this setup. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher rejects setups with closer stops; this is not an account risk percentage.",
    "summary": "Smallest stock-price distance between entry and the calculated stop allowed for this setup.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "displacement_fraction": {
    "label": "Required distance above VWAP (fraction)",
    "meaning": "Required stock-price distance above VWAP at the checkpoint. Enter a fraction: 0.01 means 1%.",
    "effect": "Higher requires a stronger move above VWAP.",
    "summary": "Required stock-price distance above VWAP at the checkpoint.",
    "detail": "Enter a fraction: 0.01 means 1%."
  },
  "min_gap_atr": {
    "label": "Minimum price gap (times ATR)",
    "meaning": "Smallest fair value gap, a gap between the relevant candles, compared with typical movement.",
    "effect": "Higher skips smaller gaps.",
    "summary": "Smallest fair value gap, a gap between the relevant candles, compared with typical movement.",
    "detail": ""
  },
  "min_compression_bars": {
    "label": "Minimum tight-range candles",
    "meaning": "How many candles must be available in the compression window.",
    "effect": "Higher requires more candles before the setup can qualify.",
    "summary": "How many candles must be available in the compression window.",
    "detail": ""
  },
  "max_base_atr_multiple": {
    "label": "Maximum base width (times ATR)",
    "meaning": "Largest permitted base range relative to typical candle movement.",
    "effect": "Lower requires a tighter base.",
    "summary": "Largest permitted base range relative to typical candle movement.",
    "detail": ""
  },
  "midpoint_fraction": {
    "label": "Range dividing point (fraction)",
    "meaning": "Where the dividing level sits between the range low and high. 0.5 is halfway.",
    "effect": "Higher moves that level toward the high and changes the relevant checks.",
    "summary": "Where the dividing level sits between the range low and high.",
    "detail": "0.5 is halfway."
  },
  "vwap_target_fraction": {
    "label": "Distance toward VWAP (fraction)",
    "meaning": "Where the chart target lies between entry and VWAP. 1 reaches VWAP; 0.5 goes halfway.",
    "effect": "Higher places the target farther toward VWAP. Whether it closes a trade depends on the active exit.",
    "summary": "Where the chart target lies between entry and VWAP.",
    "detail": "1 reaches VWAP; 0.5 goes halfway."
  },
  "stop_atr": {
    "label": "Chart stop distance (times ATR)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "stop_atr_multiple": {
    "label": "Chart stop distance (times ATR)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "stop_buffer_atr": {
    "label": "Chart stop distance (times ATR)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "stop_buffer_range": {
    "label": "Chart stop distance (range fraction)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "stop_range_fraction": {
    "label": "Chart stop distance (range fraction)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "atr_trail_multiple": {
    "label": "Chart trailing distance (times ATR)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": ""
  },
  "reward_risk": {
    "label": "Chart reward-to-risk target",
    "meaning": "Target distance as a multiple of the stock entry-to-stop distance. 2 means twice that distance.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Target distance as a multiple of the stock entry-to-stop distance.",
    "detail": "2 means twice that distance."
  },
  "target_r": {
    "label": "Chart reward-to-risk target",
    "meaning": "Target distance as a multiple of the stock entry-to-stop distance. 2 means twice that distance.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Target distance as a multiple of the stock entry-to-stop distance.",
    "detail": "2 means twice that distance."
  },
  "target_risk_ratio": {
    "label": "Chart reward-to-risk target",
    "meaning": "Target distance as a multiple of the stock entry-to-stop distance. 2 means twice that distance.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Target distance as a multiple of the stock entry-to-stop distance.",
    "detail": "2 means twice that distance."
  },
  "minimum_reward_risk": {
    "label": "Minimum reward-to-risk ratio",
    "meaning": "Required room to the chart target compared with the entry-to-stop distance.",
    "effect": "Higher rejects setups with less potential room relative to their calculated risk.",
    "summary": "Required room to the chart target compared with the entry-to-stop distance.",
    "detail": ""
  },
  "require_first_retest": {
    "label": "Require the first retest",
    "meaning": "Only accepts the first return to the price gap after it forms.",
    "effect": "On rejects a gap that price already touched earlier; off allows later retests.",
    "summary": "Only accepts the first return to the price gap after it forms.",
    "detail": ""
  },
  "require_directional_confirmation": {
    "label": "Require a candle in the trade direction",
    "meaning": "Requires the strategy's directional candle confirmation.",
    "effect": "On adds a confirmation requirement; off permits setups without it.",
    "summary": "Requires the strategy's directional candle confirmation.",
    "detail": ""
  },
  "require_midpoint_close": {
    "label": "Require a close past the midpoint",
    "meaning": "Requires the retest candle to close above the gap midpoint for calls, or below it for puts.",
    "effect": "On requires this recovery within the gap; off removes the midpoint-close check.",
    "summary": "Requires the retest candle to close above the gap midpoint for calls, or below it for puts.",
    "detail": ""
  },
  "macd_fast": {
    "label": "MACD fast average (candles)",
    "meaning": "MACD compares price averages to help judge momentum. This sets the candle count for this part.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Candle count for this part of the momentum check.",
    "detail": "MACD compares price averages to help judge momentum. This sets the candle count for this part."
  },
  "macd_slow": {
    "label": "MACD slow average (candles)",
    "meaning": "MACD compares price averages to help judge momentum. This sets the candle count for this part.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Candle count for this part of the momentum check.",
    "detail": "MACD compares price averages to help judge momentum. This sets the candle count for this part."
  },
  "macd_signal": {
    "label": "MACD signal average (candles)",
    "meaning": "MACD compares price averages to help judge momentum. This sets the candle count for this part.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Candle count for this part of the momentum check.",
    "detail": "MACD compares price averages to help judge momentum. This sets the candle count for this part."
  },
  "rsi_period": {
    "label": "RSI lookback (candles)",
    "meaning": "RSI compares recent upward and downward moves on a scale of 0 to 100.",
    "effect": "More candles smooth changes; fewer react faster.",
    "summary": "Number of candles used to compare upward and downward moves.",
    "detail": "RSI compares recent upward and downward moves on a scale of 0 to 100."
  },
  "rsi_ceiling": {
    "label": "Highest allowed RSI",
    "meaning": "The upper RSI reading accepted by this bearish setup.",
    "effect": "Lower requires a weaker reading and can reject more entries.",
    "summary": "The upper RSI reading accepted by this bearish setup.",
    "detail": ""
  },
  "band_period": {
    "label": "Price band lookback (candles)",
    "meaning": "How much price history is used to calculate the squeeze bands.",
    "effect": "More candles use a longer history and can change when a squeeze qualifies.",
    "summary": "How much price history is used to calculate the squeeze bands.",
    "detail": ""
  },
  "band_deviations": {
    "label": "Price band width",
    "meaning": "Width of the price bands measured in units of recent price variation.",
    "effect": "Higher widens these bands and changes the squeeze test.",
    "summary": "Width of the price bands measured in units of recent price variation.",
    "detail": ""
  },
  "channel_atr_multiple": {
    "label": "Channel distance (times ATR)",
    "meaning": "Distance of the channel or VWAP bands using typical candle movement.",
    "effect": "Higher widens the channel and changes the movement needed to reach its edges.",
    "summary": "Distance of the channel or VWAP bands using typical candle movement.",
    "detail": ""
  },
  "band_atr": {
    "label": "Channel distance (times ATR)",
    "meaning": "Distance of the channel or VWAP bands using typical candle movement.",
    "effect": "Higher widens the channel and changes the movement needed to reach its edges.",
    "summary": "Distance of the channel or VWAP bands using typical candle movement.",
    "detail": ""
  },
  "risk_per_trade": {
    "label": "Risk per trade (%)",
    "meaning": "Share of account value used as the risk budget for sizing one trade.",
    "effect": "Higher can buy more contracts and increase losses. The risk estimate is not a guaranteed maximum loss.",
    "summary": "Share of account value used as the risk budget for sizing one trade.",
    "detail": ""
  },
  "max_position_dollars_pct": {
    "label": "Maximum position cost (% of account)",
    "meaning": "Caps how much of the account can pay for this position's option contracts.",
    "effect": "Higher permits a more expensive position; other sizing and buying-power limits still apply.",
    "summary": "Caps how much of the account can pay for this position's option contracts.",
    "detail": ""
  },
  "partial_sell_pct": {
    "label": "Contracts sold at first target (%)",
    "meaning": "Share of the position sold when the first profit target is reached.",
    "effect": "Higher sells more early and leaves fewer contracts to trail. Whole-contract rounding applies.",
    "summary": "Share of the position sold when the first profit target is reached.",
    "detail": "The first sale rounds down to whole contracts. If it rounds to zero, all contracts trail after activation."
  },
  "gain_pct": {
    "label": "First profit target (%)",
    "meaning": "Option-price gain from entry needed for the first sale. Example: +10% on a $2 option is $2.20.",
    "effect": "Higher waits for a larger gain; lower can take profit sooner. Reaching it is not guaranteed.",
    "summary": "Option-price gain from entry needed for the first sale.",
    "detail": "Example: +10% on a $2 option is $2.20."
  },
  "partial_gain_pct": {
    "label": "First profit target (%)",
    "meaning": "Option-price gain from entry needed for the first sale. Example: +10% on a $2 option is $2.20.",
    "effect": "Higher waits for a larger gain; lower can take profit sooner. Reaching it is not guaranteed.",
    "summary": "Option-price gain from entry needed for the first sale.",
    "detail": "Example: +10% on a $2 option is $2.20."
  },
  "giveback_pct": {
    "label": "Peak profit allowed back (%)",
    "meaning": "How much of the highest profit may disappear before selling. Example: 10% of $30 peak profit is $3.",
    "effect": "Higher allows a larger retreat; lower follows profit more tightly. This is profit percentage, not option-price percentage.",
    "summary": "How much of the highest profit may disappear before selling.",
    "detail": "Example: 10% of $30 peak profit is $3."
  },
  "legacy_giveback_pct": {
    "label": "Peak profit allowed back (%)",
    "meaning": "How much of the highest profit may disappear before selling. Example: 10% of $30 peak profit is $3.",
    "effect": "Higher allows a larger retreat; lower follows profit more tightly. This is profit percentage, not option-price percentage.",
    "summary": "How much of the highest profit may disappear before selling.",
    "detail": "Example: 10% of $30 peak profit is $3."
  },
  "timeframe_minutes": {
    "label": "Fail-safe candle length (minutes)",
    "meaning": "Length of each completed stock candle used by the fail-safe.",
    "effect": "Longer candles take longer to confirm. The option-loss condition must also pass.",
    "summary": "Length of each completed stock candle used by the fail-safe.",
    "detail": ""
  },
  "consecutive_candles": {
    "label": "Candles moving against the trade",
    "meaning": "Consecutive closes lower than the previous close for calls, or higher for puts.",
    "effect": "More candles require a longer adverse sequence before an exit can trigger.",
    "summary": "Consecutive closes lower than the previous close for calls, or higher for puts.",
    "detail": ""
  },
  "loss_pct": {
    "label": "Option loss needed (%)",
    "meaning": "How far the option bid must fall below entry before the fail-safe can exit.",
    "effect": "Higher tolerates a larger loss. The adverse-candle condition must also pass; sale price can differ.",
    "summary": "How far the option bid must fall below entry before the fail-safe can exit.",
    "detail": ""
  },
  "minimum_dte": {
    "label": "Earliest expiration (days)",
    "meaning": "Minimum days remaining before the option expires.",
    "effect": "Higher excludes nearer expirations.",
    "summary": "Minimum days remaining before the option expires.",
    "detail": ""
  },
  "maximum_dte": {
    "label": "Latest expiration (days)",
    "meaning": "Maximum days remaining before the option expires.",
    "effect": "Lower excludes farther expirations.",
    "summary": "Maximum days remaining before the option expires.",
    "detail": ""
  },
  "minimum_premium": {
    "label": "Lowest option price ($ per share)",
    "meaning": "Lowest option premium allowed in the contract search. $2 per share means $200 per contract.",
    "effect": "Higher excludes cheaper contracts.",
    "summary": "Lowest option premium allowed in the contract search. $2 per share means $200 per contract.",
    "detail": ""
  },
  "maximum_premium": {
    "label": "Highest option price ($ per share)",
    "meaning": "Highest option premium allowed in the contract search. $2 per share means $200 per contract.",
    "effect": "Lower excludes more expensive contracts.",
    "summary": "Highest option premium allowed in the contract search. $2 per share means $200 per contract.",
    "detail": ""
  },
  "maximum_spread_pct": {
    "label": "Largest bid/ask gap (fraction)",
    "meaning": "Limits the relative gap between what buyers bid and sellers ask. Enter 0.08 for 8%.",
    "effect": "Lower demands a tighter market and can leave fewer eligible contracts.",
    "summary": "Limits the relative gap between what buyers bid and sellers ask.",
    "detail": "Enter 0.08 for 8%."
  },
  "maximum_spread_dollars": {
    "label": "Largest bid/ask gap ($ per share)",
    "meaning": "Dollar cap on the gap between bid and ask. Zero disables this dollar cap.",
    "effect": "A smaller positive cap is stricter. It does not remove the separate percentage limit.",
    "summary": "Dollar cap on the gap between bid and ask.",
    "detail": "Zero disables this dollar cap."
  },
  "minimum_open_interest": {
    "label": "Minimum outstanding contracts",
    "meaning": "Minimum number of contracts still open in the market, called open interest. Zero sets no minimum.",
    "effect": "Higher can exclude less established contracts; it does not guarantee an immediate fill.",
    "summary": "Minimum number of contracts still open in the market, called open interest.",
    "detail": "Zero sets no minimum."
  },
  "primary_policy": {
    "label": "Choose among eligible contracts",
    "meaning": "Ranks contracts that have already passed the filters.",
    "effect": "Changing this can select a different strike or expiration; it does not remove eligibility checks.",
    "summary": "Ranks contracts that have already passed the filters.",
    "detail": ""
  },
  "target_minimum_premium": {
    "label": "Target ranking: lowest price ($ per share)",
    "meaning": "Lower price boundary for the target-price contract choice.",
    "effect": "Higher narrows that choice from the cheaper end.",
    "summary": "Lower price boundary for the target-price contract choice.",
    "detail": ""
  },
  "target_maximum_premium": {
    "label": "Target ranking: highest price ($ per share)",
    "meaning": "Upper price boundary for the target-price contract choice.",
    "effect": "Lower narrows that choice from the expensive end.",
    "summary": "Upper price boundary for the target-price contract choice.",
    "detail": ""
  },
  "target_premium": {
    "label": "Target ranking: preferred price ($ per share)",
    "meaning": "Preferred option price when using the target-price ranking.",
    "effect": "Changing it favors contracts nearer that price within the allowed range.",
    "summary": "Preferred option price when using the target-price ranking.",
    "detail": ""
  },
  "hold_minutes": {
    "label": "Time limit (minutes)",
    "meaning": "Elapsed time after entry before this timer requests an exit.",
    "effect": "Lower requests an earlier exit; higher holds longer. Safety and session-close exits still apply.",
    "summary": "Elapsed time after entry before this timer requests an exit.",
    "detail": ""
  },
  "max_hold_bars": {
    "label": "Time limit (completed candles)",
    "meaning": "Maximum candles held under the native exit.",
    "effect": "Higher permits a longer hold; candle length also affects elapsed time.",
    "summary": "Maximum candles held under the native exit.",
    "detail": ""
  },
  "missing_structure_hold_minutes": {
    "label": "Missing-level fallback (minutes)",
    "meaning": "Fallback hold limit when the native rule has no usable structural level.",
    "effect": "Lower requests an earlier fallback exit. It does not repair missing chart data.",
    "summary": "Fallback hold limit when the native rule has no usable structural level.",
    "detail": ""
  },
  "legacy_arm_dollars": {
    "label": "Start profit protection ($ per contract)",
    "meaning": "Profit per contract required to start the native profit trail.",
    "effect": "Higher waits for more profit before protection arms; below it this trail does not protect the trade.",
    "summary": "Profit per contract required to start the native profit trail.",
    "detail": ""
  },
  "final_gain_pct": {
    "label": "Final profit target (%)",
    "meaning": "Option gain from entry at which the native policy requests the final sale.",
    "effect": "Higher waits for a larger gain and can leave the trade open longer.",
    "summary": "Option gain from entry at which the native policy requests the final sale.",
    "detail": ""
  },
  "reclaim_ema_period": {
    "label": "Reclaim average (candles)",
    "meaning": "Candle count for the price average the stock must reclaim.",
    "effect": "Higher makes this average slower to react and can change when a reclaim qualifies.",
    "summary": "Candle count for the price average the stock must reclaim.",
    "detail": ""
  }
};
