// Display-only explanations. Never used to set defaults or execute trades.
export const settingHelp = {
  "allow_long": {
    "label": "Allow trades expecting a rise",
    "meaning": "Lets the bot consider trades that benefit when the stock rises. Example: a call setup can qualify when this is on. The other entry checks still have to pass.",
    "effect": "Off skips entries expecting a rise for this strategy and ticker; it does not close existing positions.",
    "summary": "Lets the bot consider trades that benefit when the stock rises.",
    "detail": "Example: a call setup can qualify when this is on. The other entry checks still have to pass."
  },
  "allow_short": {
    "label": "Allow trades expecting a fall",
    "meaning": "Lets the bot consider trades that benefit when the stock falls. Example: a put setup can qualify when this is on. This does not mean selling shares short.",
    "effect": "Off skips entries expecting a fall; it does not close existing positions.",
    "summary": "Lets the bot consider trades that benefit when the stock falls.",
    "detail": "Example: a put setup can qualify when this is on. This does not mean selling shares short."
  },
  "entry_timeframe_minutes": {
    "label": "Entry candle length (minutes)",
    "meaning": "Minutes of stock prices grouped into each candle for entry checks. Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended.",
    "effect": "Longer candles update less often; shorter candles react sooner and include more small price moves.",
    "summary": "Minutes of stock prices grouped into each candle for entry checks.",
    "detail": "Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended."
  },
  "context_timeframe_minutes": {
    "label": "Trend candle length (minutes)",
    "meaning": "Minutes of stock prices grouped into each candle for trend checks. Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended.",
    "effect": "Longer candles give a slower view of the trend and need more history.",
    "summary": "Minutes of stock prices grouped into each candle for trend checks.",
    "detail": "Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended."
  },
  "structural_timeframe_minutes": {
    "label": "Exit candle length (minutes)",
    "meaning": "Minutes of stock prices grouped into each candle for chart exits. Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended.",
    "effect": "Longer candles can delay confirmation of a break; shorter candles check more often.",
    "summary": "Minutes of stock prices grouped into each candle for chart exits.",
    "detail": "Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended."
  },
  "fast_ema": {
    "label": "Fast trend average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "slow_ema": {
    "label": "Slow trend average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "pullback_ema": {
    "label": "Pullback crossing average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "pullback_limit_ema": {
    "label": "Pullback depth average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "trend_ema": {
    "label": "Main trend average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "ema_bars": {
    "label": "Price average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  },
  "atr_bars": {
    "label": "Candles used to measure usual price movement",
    "meaning": "Sets how much recent history estimates the stock’s usual movement. Example: 14 uses 14 candles as the movement setting. The estimate, called ATR, helps turn distance settings into dollars. It includes gaps between candles.",
    "effect": "More candles smooth the estimate; fewer make it react faster. Other distances based on ATR change with it.",
    "summary": "Sets how much recent history estimates the stock’s usual movement.",
    "detail": "Example: 14 uses 14 candles as the movement setting. The estimate, called ATR, helps turn distance settings into dollars. It includes gaps between candles."
  },
  "atr_period": {
    "label": "Candles used to measure usual price movement",
    "meaning": "Sets how much recent history estimates the stock’s usual movement. Example: 14 uses 14 candles as the movement setting. The estimate, called ATR, helps turn distance settings into dollars. It includes gaps between candles.",
    "effect": "More candles smooth the estimate; fewer make it react faster. Other distances based on ATR change with it.",
    "summary": "Sets how much recent history estimates the stock’s usual movement.",
    "detail": "Example: 14 uses 14 candles as the movement setting. The estimate, called ATR, helps turn distance settings into dollars. It includes gaps between candles."
  },
  "daily_atr_period": {
    "label": "Days used to measure usual price movement",
    "meaning": "Sets how much daily history estimates the stock’s usual movement. Example: 14 uses a 14-day movement setting. This measures stock movement, not the profit on an option.",
    "effect": "A longer history changes more slowly and can change whether the prior range qualifies.",
    "summary": "Sets how much daily history estimates the stock’s usual movement.",
    "detail": "Example: 14 uses a 14-day movement setting. This measures stock movement, not the profit on an option."
  },
  "use_rma_atr": {
    "label": "Smooth the price-movement estimate",
    "meaning": "Chooses how the bot averages changes in stock price. On uses Wilder’s smoothing, also called RMA. Off uses this strategy’s other averaging method. Both use price history; they can produce different trend lines.",
    "effect": "Switching changes the trend band calculation and can move reversal signals.",
    "summary": "Chooses how the bot averages changes in stock price.",
    "detail": "On uses Wilder’s smoothing, also called RMA. Off uses this strategy’s other averaging method. Both use price history; they can produce different trend lines."
  },
  "multiplier": {
    "label": "Distance of the trend lines (times usual movement)",
    "meaning": "Sets how far the trend bands sit from the stock price using typical movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Larger bands generally need a bigger move to reverse the trend signal.",
    "summary": "Sets how far the trend bands sit from the stock price using typical movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "entry_start": {
    "label": "Start looking for new trades (Eastern)",
    "meaning": "Start looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Start looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "start": {
    "label": "Start looking for new trades (Eastern)",
    "meaning": "Start looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Start looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "start_time": {
    "label": "Start looking for new trades (Eastern)",
    "meaning": "Start looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Start looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "entry_end": {
    "label": "Stop looking for new trades (Eastern)",
    "meaning": "Stop looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Stop looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "end": {
    "label": "Stop looking for new trades (Eastern)",
    "meaning": "Stop looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Stop looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "end_time": {
    "label": "Stop looking for new trades (Eastern)",
    "meaning": "Stop looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Stop looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "entry_deadline": {
    "label": "Stop looking for new trades (Eastern)",
    "meaning": "Stop looking for new trades using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Stop looking for new trades using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "breakout_deadline": {
    "label": "Latest time for the first range break (Eastern)",
    "meaning": "Latest time for the first range break using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Latest time for the first range break using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "failure_deadline": {
    "label": "Latest time for a failed range break (Eastern)",
    "meaning": "Latest time for a failed range break using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Latest time for a failed range break using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "base_start": {
    "label": "Start measuring the price range (Eastern)",
    "meaning": "Start measuring the price range using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Start measuring the price range using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "base_end": {
    "label": "Finish measuring the price range (Eastern)",
    "meaning": "Finish measuring the price range using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Finish measuring the price range using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "compression_start": {
    "label": "Start measuring the tight price range (Eastern)",
    "meaning": "Start measuring the tight price range using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Start measuring the tight price range using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "compression_end": {
    "label": "Finish measuring the tight price range (Eastern)",
    "meaning": "Finish measuring the tight price range using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Finish measuring the tight price range using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "displacement_checkpoint": {
    "label": "Time to check price above VWAP (Eastern)",
    "meaning": "Time to check price above VWAP using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Time to check price above VWAP using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "reference_time": {
    "label": "Time of the comparison candle (Eastern)",
    "meaning": "Time of the comparison candle using New York time. Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time.",
    "effect": "An earlier or later time changes which candles this step can use. An entry cutoff does not close an existing trade.",
    "summary": "Time of the comparison candle using New York time.",
    "detail": "Example: 10:30 means 10:30 AM Eastern, even if you live in another time zone. This changes this step’s timing, not the market’s opening or closing time."
  },
  "active_date": {
    "label": "Only trade on this date",
    "meaning": "Limits new trades to one chosen date. Example: choosing November 16 allows this strategy to enter only on that date. Leave it blank to avoid this date restriction.",
    "effect": "Setting a date excludes entries on every other date.",
    "summary": "Limits new trades to one chosen date.",
    "detail": "Example: choosing November 16 allows this strategy to enter only on that date. Leave it blank to avoid this date restriction."
  },
  "opening_range_minutes": {
    "label": "Minutes used for the opening high and low",
    "meaning": "Measures the highest and lowest stock prices after the market opens. Example: 15 measures the first 15 minutes after 9:30 AM Eastern, ending at 9:45 AM.",
    "effect": "A longer window waits longer before a breakout can qualify and changes the range levels.",
    "summary": "Measures the highest and lowest stock prices after the market opens.",
    "detail": "Example: 15 measures the first 15 minutes after 9:30 AM Eastern, ending at 9:45 AM."
  },
  "opening_bars": {
    "label": "Opening candles to measure",
    "meaning": "Counts opening candles before checking the opening price move. Example: 3 five-minute candles cover the first 15 minutes. The candle length determines the total time.",
    "effect": "A larger count moves the evaluation later and changes the measured opening move.",
    "summary": "Counts opening candles before checking the opening price move.",
    "detail": "Example: 3 five-minute candles cover the first 15 minutes. The candle length determines the total time."
  },
  "breakout_bars": {
    "label": "Candles checked for a breakout",
    "meaning": "How many candles the bot checks to find a high or low for price to break. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find a high or low for price to break.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "scan_bars": {
    "label": "Candles searched for a price gap",
    "meaning": "How many candles the bot checks to find a gap between candles. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find a gap between candles.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "channel_bars": {
    "label": "Candles used for the earlier range",
    "meaning": "How many candles the bot checks to find the high and low before a strong move. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find the high and low before a strong move.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "range_bars": {
    "label": "Candles used for the price range",
    "meaning": "How many candles the bot checks to find a range price can break and return to. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find a range price can break and return to.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "lookback_bars": {
    "label": "Candles checked for earlier highs and lows",
    "meaning": "How many candles the bot checks to find an earlier high or low for a reversal. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find an earlier high or low for a reversal.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "prior_extreme_lookback_bars": {
    "label": "Candles used for chart levels",
    "meaning": "How many candles the bot checks to find highs and lows used as chart levels. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find highs and lows used as chart levels.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "volume_lookback_bars": {
    "label": "Candles used for average trading volume",
    "meaning": "How many candles the bot checks to find the average number of shares traded. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change which setup passes; fewer focus on more recent activity.",
    "summary": "How many candles the bot checks to find the average number of shares traded.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "pivot_lookback": {
    "label": "Candles needed to confirm a turning point",
    "meaning": "Requires candles on both sides of a possible high or low. Example: 2 needs two candles before and two after the turning point. The bot cannot confirm it until the two later candles have closed.",
    "effect": "A larger number confirms swings later and can filter out smaller turns.",
    "summary": "Requires candles on both sides of a possible high or low.",
    "detail": "Example: 2 needs two candles before and two after the turning point. The bot cannot confirm it until the two later candles have closed."
  },
  "narrow_range_days": {
    "label": "Days compared for a tight price range",
    "meaning": "Checks whether the previous day had an unusually small high-to-low range. Example: 7 compares daily ranges across seven days.",
    "effect": "More days make the narrow-range comparison cover a longer history.",
    "summary": "Checks whether the previous day had an unusually small high-to-low range.",
    "detail": "Example: 7 compares daily ranges across seven days."
  },
  "slope_bars": {
    "label": "Candles back to check VWAP direction",
    "meaning": "Checks whether the VWAP line has risen or fallen. Example: 5 compares VWAP now with its value five candles earlier. VWAP is the average stock price weighted by how many shares traded.",
    "effect": "A larger count measures direction over a longer stretch; a smaller count reacts to recent changes.",
    "summary": "Checks whether the VWAP line has risen or fallen.",
    "detail": "Example: 5 compares VWAP now with its value five candles earlier. VWAP is the average stock price weighted by how many shares traded."
  },
  "efficiency_period": {
    "label": "Candles used to judge a steady move",
    "meaning": "Measures steady progress versus back-and-forth movement. Example: moving directly from $100 to $102 is steadier than reaching $102 after several rises and falls.",
    "effect": "More candles judge a longer trend; fewer emphasize recent movement.",
    "summary": "Measures steady progress versus back-and-forth movement.",
    "detail": "Example: moving directly from $100 to $102 is steadier than reaching $102 after several rises and falls."
  },
  "efficiency_minimum": {
    "label": "Minimum steadiness of the move (0 to 1)",
    "meaning": "Requires enough progress in one direction. Example: 0.5 means the final move must be at least half the total distance traveled. A $2 net move over $4 of rises and falls scores 0.5.",
    "effect": "Higher is stricter and can allow fewer setups; lower accepts more choppy movement.",
    "summary": "Requires enough progress in one direction.",
    "detail": "Example: 0.5 means the final move must be at least half the total distance traveled. A $2 net move over $4 of rises and falls scores 0.5."
  },
  "maximum_efficiency": {
    "label": "Maximum steadiness of the move (0 to 1)",
    "meaning": "Looks for back-and-forth price movement rather than a steady trend. Example: a $2 net move over $4 of rises and falls scores 0.5. A lower limit requires more back-and-forth movement.",
    "effect": "Lower requires more back-and-forth movement; higher accepts more directional ranges.",
    "summary": "Looks for back-and-forth price movement rather than a steady trend.",
    "detail": "Example: a $2 net move over $4 of rises and falls scores 0.5. A lower limit requires more back-and-forth movement."
  },
  "volume_ratio_minimum": {
    "label": "Trading volume needed compared with usual",
    "meaning": "Requires this many times the average number of shares traded. Example: 1.5 requires 15,000 shares when the comparison average is 10,000. Enter 1 for the same as average.",
    "effect": "Higher requires busier candles and can reject more entries.",
    "summary": "Requires this many times the average number of shares traded.",
    "detail": "Example: 1.5 requires 15,000 shares when the comparison average is 10,000. Enter 1 for the same as average."
  },
  "close_location_minimum": {
    "label": "How near the candle’s end price is to its high or low",
    "meaning": "Requires a strong finish near the end of the candle’s range. Example: with a $100 low and $104 high, 0.75 requires a bullish close at $103 or higher. A bearish close must be at $101 or lower.",
    "effect": "Higher requires a stronger close near the high for calls or low for puts.",
    "summary": "Requires a strong finish near the end of the candle’s range.",
    "detail": "Example: with a $100 low and $104 high, 0.75 requires a bullish close at $103 or higher. A bearish close must be at $101 or lower."
  },
  "impulse_atr": {
    "label": "Smallest strong price move (times usual movement)",
    "meaning": "The strong move must be large enough compared with typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher demands a larger strong move and can allow fewer setups.",
    "summary": "The strong move must be large enough compared with typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "impulse_range_atr": {
    "label": "Smallest strong price move (times usual movement)",
    "meaning": "The strong move must be large enough compared with typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher demands a larger strong move and can allow fewer setups.",
    "summary": "The strong move must be large enough compared with typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "pullback_min_atr": {
    "label": "Smallest pullback (times usual movement)",
    "meaning": "Smallest allowed pullback compared with typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher skips shallower pullbacks.",
    "summary": "Smallest allowed pullback compared with typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "pullback_max_atr": {
    "label": "Largest pullback (times usual movement)",
    "meaning": "Largest allowed pullback compared with typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher permits deeper pullbacks; lower rejects them sooner.",
    "summary": "Largest allowed pullback compared with typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "minimum_pullback_bars": {
    "label": "Fewest candles in a pullback",
    "meaning": "Requires the pullback to last at least this many completed candles. Example: 2 five-minute candles require two completed pullback candles before the setup can qualify.",
    "effect": "Higher requires a longer pullback before entry can qualify.",
    "summary": "Requires the pullback to last at least this many completed candles.",
    "detail": "Example: 2 five-minute candles require two completed pullback candles before the setup can qualify."
  },
  "maximum_pullback_bars": {
    "label": "Most candles to wait for a pullback",
    "meaning": "Stops waiting when the pullback takes too many candles. Example: 6 five-minute candles allow a longer wait than 3. Other entry checks still need to pass.",
    "effect": "Higher gives the setup more time; lower abandons it sooner.",
    "summary": "Stops waiting when the pullback takes too many candles.",
    "detail": "Example: 6 five-minute candles allow a longer wait than 3. Other entry checks still need to pass."
  },
  "pullback_limit_bars": {
    "label": "Most candles to wait for a pullback",
    "meaning": "Stops waiting when the pullback takes too many candles. Example: 6 five-minute candles allow a longer wait than 3. Other entry checks still need to pass.",
    "effect": "Higher gives the setup more time; lower abandons it sooner.",
    "summary": "Stops waiting when the pullback takes too many candles.",
    "detail": "Example: 6 five-minute candles allow a longer wait than 3. Other entry checks still need to pass."
  },
  "touch_tolerance_atr": {
    "label": "How close price must get to VWAP (times usual movement)",
    "meaning": "How close stock price must get to VWAP to count as a touch. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher accepts touches farther from VWAP.",
    "summary": "How close stock price must get to VWAP to count as a touch.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "failure_tolerance_atr": {
    "label": "How far price can close past VWAP (times usual movement)",
    "meaning": "Allowed close beyond VWAP line that starts at the strategy’s chosen candle before the pullback setup fails. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher tolerates a larger move against the setup before rejecting it.",
    "summary": "Allowed close beyond VWAP line that starts at the strategy’s chosen candle before the pullback setup fails.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "minimum_sweep_atr": {
    "label": "How far price must go beyond the range (times usual movement)",
    "meaning": "How far price must pass a range edge before a reclaim can qualify. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher requires a deeper overshoot.",
    "summary": "How far price must pass a range edge before a reclaim can qualify.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "rearm_distance_atr": {
    "label": "Distance needed before another setup (times usual movement)",
    "meaning": "Movement needed to allow another the range-sweep setup. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher requires a larger reset before another signal.",
    "summary": "Movement needed to allow another the range-sweep setup.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "minimum_vwap_room_atr": {
    "label": "Minimum distance to the VWAP target (times usual movement)",
    "meaning": "Required distance from entry toward the VWAP target. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher rejects setups with less room to move.",
    "summary": "Required distance from entry toward the VWAP target.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "minimum_vwap_room_range": {
    "label": "Minimum distance toward VWAP (share of range)",
    "meaning": "Required room toward VWAP compared with the opening range. Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1.",
    "effect": "Higher requires more room and can reject more setups.",
    "summary": "Required room toward VWAP compared with the opening range.",
    "detail": "Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1."
  },
  "minimum_excursion_range": {
    "label": "Minimum move beyond the opening range (share of range)",
    "meaning": "How far price must break outside the opening range. Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1.",
    "effect": "Higher requires a bigger initial breakout before a failure can qualify.",
    "summary": "How far price must break outside the opening range.",
    "detail": "Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1."
  },
  "minimum_retouch_dollars": {
    "label": "Smallest distance used for a return to the level ($)",
    "meaning": "Sets a minimum dollar distance for counting a return to the breakout level. Example: if this is $0.10 but the percentage setting gives $0.15, the bot uses 15 cents. It uses whichever distance is larger.",
    "effect": "Higher can count more distant returns to the level as touches.",
    "summary": "Sets a minimum dollar distance for counting a return to the breakout level.",
    "detail": "Example: if this is $0.10 but the percentage setting gives $0.15, the bot uses 15 cents. It uses whichever distance is larger."
  },
  "retouch_tolerance_pct": {
    "label": "How close price must return to the breakout level",
    "meaning": "Distance from the breakout level that still counts as a retest. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher accepts returns to the level farther from that level.",
    "summary": "Distance from the breakout level that still counts as a retest.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "touch_tolerance_pct": {
    "label": "How close price must get to VWAP",
    "meaning": "How near the candle must get to the VWAP line to count as a touch. Example: with 0.0015 entered (0.15%) and VWAP at $200, price must come within 30 cents of VWAP, between $199.70 and $200.30. For a call setup, the bot checks the previous candle’s low; for a put setup, its high. The dollar distance changes with VWAP.",
    "effect": "A higher number lets price stay farther from VWAP. A lower number requires price to get closer. The other entry checks still need to pass.",
    "summary": "How near the candle must get to the VWAP line to count as a touch.",
    "detail": "Example: with 0.0015 entered (0.15%) and VWAP at $200, price must come within 30 cents of VWAP, between $199.70 and $200.30. For a call setup, the bot checks the previous candle’s low; for a put setup, its high. The dollar distance changes with VWAP."
  },
  "max_compression_pct": {
    "label": "Largest width of the tight price range",
    "meaning": "Largest allowed width of the tight range relative to stock price. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Lower requires a tighter range.",
    "summary": "Largest allowed width of the tight range relative to stock price.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "min_gap_pct": {
    "label": "Smallest opening price gap",
    "meaning": "Smallest allowed opening gap relative to stock price. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher skips smaller opening gaps.",
    "summary": "Smallest allowed opening gap relative to stock price.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "min_morning_move_pct": {
    "label": "Smallest morning price move",
    "meaning": "Smallest morning move before looking for an afternoon reversal. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher requires a larger morning move.",
    "summary": "Smallest morning move before looking for an afternoon reversal.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "min_move_pct": {
    "label": "Smallest opening price move",
    "meaning": "Smallest opening move needed for the setup. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher skips smaller moves.",
    "summary": "Smallest opening move needed for the setup.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "min_range_pct": {
    "label": "Smallest opening high-to-low range",
    "meaning": "Smallest allowed opening range relative to stock price. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher skips narrower ranges.",
    "summary": "Smallest allowed opening range relative to stock price.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "max_range_pct": {
    "label": "Largest opening high-to-low range",
    "meaning": "Largest allowed opening range relative to stock price. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Lower skips wider ranges.",
    "summary": "Largest allowed opening range relative to stock price.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "breakout_buffer_pct": {
    "label": "Extra distance needed beyond the range",
    "meaning": "Required move beyond the range edge before a breakout qualifies. Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance.",
    "effect": "Higher waits for a bigger break.",
    "summary": "Required move beyond the range edge before a breakout qualifies.",
    "detail": "Enter 0.01 for 1%. Example: 1% of a $200 reference price is $2; 0.0015 means 0.15%, or 30 cents. The strategy uses its reference price to calculate the dollar distance."
  },
  "minimum_risk_pct": {
    "label": "Smallest distance from entry to the chart stop",
    "meaning": "Smallest stock-price distance between entry and the calculated stop allowed for this setup. Enter 0.01 for 1%. Example: at a $200 stock entry, 0.01 means a $2 entry-to-stop distance. This is not the amount you risk from your account.",
    "effect": "Higher rejects setups with closer chart stops. This is not an account risk percentage.",
    "summary": "Smallest stock-price distance between entry and the calculated stop allowed for this setup.",
    "detail": "Enter 0.01 for 1%. Example: at a $200 stock entry, 0.01 means a $2 entry-to-stop distance. This is not the amount you risk from your account."
  },
  "displacement_fraction": {
    "label": "Required distance above VWAP",
    "meaning": "Required stock-price distance above VWAP at the checkpoint. Enter 0.01 for 1%. Example: if VWAP is $200, 0.01 requires price to be at least $202 at the check time.",
    "effect": "Higher requires a stronger move above VWAP.",
    "summary": "Required stock-price distance above VWAP at the checkpoint.",
    "detail": "Enter 0.01 for 1%. Example: if VWAP is $200, 0.01 requires price to be at least $202 at the check time."
  },
  "min_gap_atr": {
    "label": "Smallest gap between candles (times usual movement)",
    "meaning": "Smallest fair value gap, a gap between the relevant candles, compared with typical movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher skips smaller gaps.",
    "summary": "Smallest fair value gap, a gap between the relevant candles, compared with typical movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "min_compression_bars": {
    "label": "Candles needed in the tight range",
    "meaning": "Requires enough candles to measure the narrow price range. Example: 4 requires at least four candles in the chosen time window.",
    "effect": "Higher requires more candles before the setup can qualify.",
    "summary": "Requires enough candles to measure the narrow price range.",
    "detail": "Example: 4 requires at least four candles in the chosen time window."
  },
  "max_base_atr_multiple": {
    "label": "Largest starting price range (times usual movement)",
    "meaning": "Largest permitted starting price range relative to typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Lower requires a narrower starting range.",
    "summary": "Largest permitted starting price range relative to typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "midpoint_fraction": {
    "label": "Where to divide the price range",
    "meaning": "Chooses a point between the range’s low and high. Example: for a $100 to $104 range, 0.5 puts the dividing point at $102. Enter 0.25 for $101 or 0.75 for $103.",
    "effect": "Higher moves that level toward the high and changes the relevant checks.",
    "summary": "Chooses a point between the range’s low and high.",
    "detail": "Example: for a $100 to $104 range, 0.5 puts the dividing point at $102. Enter 0.25 for $101 or 0.75 for $103."
  },
  "vwap_target_fraction": {
    "label": "How far the target is toward VWAP",
    "meaning": "Places the chart target partway or all the way toward VWAP. Example: with entry at $100 and VWAP at $104, 0.5 sets a $102 target and 1 sets a $104 target.",
    "effect": "Higher places the target farther toward VWAP. Whether it closes a trade depends on the active exit.",
    "summary": "Places the chart target partway or all the way toward VWAP.",
    "detail": "Example: with entry at $100 and VWAP at $104, 0.5 sets a $102 target and 1 sets a $104 target."
  },
  "stop_atr": {
    "label": "Chart stop distance (times usual movement)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it."
  },
  "stop_atr_multiple": {
    "label": "Chart stop distance (times usual movement)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it."
  },
  "stop_buffer_atr": {
    "label": "Extra room beyond the chart stop level (times usual movement)",
    "meaning": "Adds room beyond the chart stop level using usual price movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Adds room beyond the chart stop level using usual price movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it."
  },
  "stop_buffer_range": {
    "label": "Extra room beyond the chart stop level (share of range)",
    "meaning": "Adds room beyond the chart stop level using the opening range’s width. Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1. This level only sells when the active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Adds room beyond the chart stop level using the opening range’s width.",
    "detail": "Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1. This level only sells when the active exit rule uses it."
  },
  "stop_range_fraction": {
    "label": "How far the stop sits inside the opening range (share of range)",
    "meaning": "Places the chart stop inside the opening high-to-low range. Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1. At 0.5, the calculated stop is halfway inside that range, at $101. This level only sells when the active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Places the chart stop inside the opening high-to-low range.",
    "detail": "Example: if the opening high is $102 and the low is $100, the range is $2. Entering 0.1 means 20 cents; 0.5 means $1. At 0.5, the calculated stop is halfway inside that range, at $101. This level only sells when the active exit rule uses it."
  },
  "atr_trail_multiple": {
    "label": "Distance of the moving chart stop (times usual movement)",
    "meaning": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it.",
    "effect": "Higher generally gives price more room. It only triggers an exit when the active exit policy uses that chart stop.",
    "summary": "Sets the distance used to calculate the strategy's stock-price stop or trailing reference.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes. This is a stock-price level. It only sells when the trade’s active exit rule uses it."
  },
  "reward_risk": {
    "label": "Target distance compared with stop distance",
    "meaning": "Sets how far the stock target sits compared with the stock stop. Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Sets how far the stock target sits compared with the stock stop.",
    "detail": "Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit."
  },
  "target_r": {
    "label": "Target distance compared with stop distance",
    "meaning": "Sets how far the stock target sits compared with the stock stop. Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Sets how far the stock target sits compared with the stock stop.",
    "detail": "Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit."
  },
  "target_risk_ratio": {
    "label": "Target distance compared with stop distance",
    "meaning": "Sets how far the stock target sits compared with the stock stop. Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit.",
    "effect": "Higher puts the target farther away. It is not a promised return, and only controls exits if the active policy uses it.",
    "summary": "Sets how far the stock target sits compared with the stock stop.",
    "detail": "Example: entry at $100 with a $99 stop is $1 apart. Entering 2 places a bullish target $2 above entry, at $102. A bearish target is below entry. This is not a promised option profit."
  },
  "minimum_reward_risk": {
    "label": "Minimum target room compared with stop room",
    "meaning": "Rejects a setup if the target is too close compared with the stop. Example: if the stop is $1 from entry, a setting of 2 requires at least $2 of room toward the target.",
    "effect": "Higher rejects setups with less potential room relative to their calculated risk.",
    "summary": "Rejects a setup if the target is too close compared with the stop.",
    "detail": "Example: if the stop is $1 from entry, a setting of 2 requires at least $2 of room toward the target."
  },
  "require_first_retest": {
    "label": "Only use the first return to the gap",
    "meaning": "Accepts the first return to a price gap, not a later return. Example: if price has already returned to the gap once, turning this on rejects the next return.",
    "effect": "On rejects a gap that price already touched earlier; off allows later returns to the level.",
    "summary": "Accepts the first return to a price gap, not a later return.",
    "detail": "Example: if price has already returned to the gap once, turning this on rejects the next return."
  },
  "require_directional_confirmation": {
    "label": "Require a candle supporting the trade",
    "meaning": "Adds the strategy’s candle-direction check before entering. Example: a bullish setup needs its bullish candle check to pass. The exact check belongs to this strategy; turning this off removes only this requirement.",
    "effect": "On adds a confirmation requirement; off permits setups without it.",
    "summary": "Adds the strategy’s candle-direction check before entering.",
    "detail": "Example: a bullish setup needs its bullish candle check to pass. The exact check belongs to this strategy; turning this off removes only this requirement."
  },
  "require_midpoint_close": {
    "label": "Require price to finish past the middle of the gap",
    "meaning": "Requires a close above the gap’s middle for calls, or below it for puts. Example: a gap from $100 to $102 has its middle at $101. A call needs a close above $101; a put needs a close below $101.",
    "effect": "On requires this recovery within the gap; off removes the midpoint-close check.",
    "summary": "Requires a close above the gap’s middle for calls, or below it for puts.",
    "detail": "Example: a gap from $100 to $102 has its middle at $101. A call needs a close above $101; a put needs a close below $101."
  },
  "macd_fast": {
    "label": "MACD fast average (candles)",
    "meaning": "Sets the speed of this part of the MACD momentum check. MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Sets the speed of this part of the MACD momentum check.",
    "detail": "MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly."
  },
  "macd_slow": {
    "label": "MACD slow average (candles)",
    "meaning": "Sets the speed of this part of the MACD momentum check. MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Sets the speed of this part of the MACD momentum check.",
    "detail": "MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly."
  },
  "macd_signal": {
    "label": "MACD signal average (candles)",
    "meaning": "Sets the speed of this part of the MACD momentum check. MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly.",
    "effect": "Larger counts respond more slowly; smaller counts react faster and can change confirmation timing.",
    "summary": "Sets the speed of this part of the MACD momentum check.",
    "detail": "MACD compares faster and slower price averages. Example: a 12-candle setting reacts sooner than a 26-candle setting. The signal setting smooths the comparison line, rather than the stock price directly."
  },
  "rsi_period": {
    "label": "Candles used for RSI",
    "meaning": "Sets how much history compares rising prices with falling prices. RSI is a 0 to 100 reading of recent gains versus losses. Example: 14 uses a 14-candle setting. It does not mean a 14% gain or a guaranteed reversal.",
    "effect": "More candles smooth changes; fewer react faster.",
    "summary": "Sets how much history compares rising prices with falling prices.",
    "detail": "RSI is a 0 to 100 reading of recent gains versus losses. Example: 14 uses a 14-candle setting. It does not mean a 14% gain or a guaranteed reversal."
  },
  "rsi_ceiling": {
    "label": "Highest allowed RSI",
    "meaning": "Rejects this bearish setup when RSI is above this number. Example: with a limit of 50, RSI at 55 fails this check. Passing this check alone does not place an order.",
    "effect": "Lower requires a weaker reading and can reject more entries.",
    "summary": "Rejects this bearish setup when RSI is above this number.",
    "detail": "Example: with a limit of 50, RSI at 55 fails this check. Passing this check alone does not place an order."
  },
  "band_period": {
    "label": "Candles used for price bands",
    "meaning": "How many candles the bot checks to find the usual price range. Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes.",
    "effect": "More candles use a longer history and can change when a squeeze qualifies.",
    "summary": "How many candles the bot checks to find the usual price range.",
    "detail": "Example: 20 five-minute candles cover 100 minutes of price history. This number counts candles, not minutes."
  },
  "band_deviations": {
    "label": "Width of the price bands",
    "meaning": "Sets how far the outer lines sit from the average price. Example: if the measured price variation is $1, a setting of 2 puts the bands $2 away from the average. This uses statistical price variation, not ATR.",
    "effect": "Higher widens these bands and changes the squeeze test.",
    "summary": "Sets how far the outer lines sit from the average price.",
    "detail": "Example: if the measured price variation is $1, a setting of 2 puts the bands $2 away from the average. This uses statistical price variation, not ATR."
  },
  "channel_atr_multiple": {
    "label": "Distance of the outer price lines (times usual movement)",
    "meaning": "Distance of the channel or VWAP bands using typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher widens the channel and changes the movement needed to reach its edges.",
    "summary": "Distance of the channel or VWAP bands using typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "band_atr": {
    "label": "Distance of the outer price lines (times usual movement)",
    "meaning": "Distance of the channel or VWAP bands using typical candle movement. Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes.",
    "effect": "Higher widens the channel and changes the movement needed to reach its edges.",
    "summary": "Distance of the channel or VWAP bands using typical candle movement.",
    "detail": "Example: if usual movement (ATR) is $1, entering 0.5 means 50 cents and entering 2 means $2. This distance changes as usual movement changes."
  },
  "risk_per_trade": {
    "label": "Risk budget for one trade (%)",
    "meaning": "Sets the account amount used to calculate how many contracts to buy. Example: 1% of a $10,000 account is a $100 risk budget. At an estimated $25 risk per contract, that allows four contracts before other limits. Actual losses can exceed the estimate.",
    "effect": "Higher can buy more contracts and increase losses. The risk estimate is not a guaranteed maximum loss.",
    "summary": "Sets the account amount used to calculate how many contracts to buy.",
    "detail": "Example: 1% of a $10,000 account is a $100 risk budget. At an estimated $25 risk per contract, that allows four contracts before other limits. Actual losses can exceed the estimate."
  },
  "max_position_dollars_pct": {
    "label": "Most of the account to spend on one trade (%)",
    "meaning": "Caps how much you can pay for one position. Example: 10% of a $10,000 account is $1,000. A $2 option costs $200 per standard contract, so that cap allows at most five before fees and other limits.",
    "effect": "Higher permits a more expensive position; other sizing and buying-power limits still apply.",
    "summary": "Caps how much you can pay for one position.",
    "detail": "Example: 10% of a $10,000 account is $1,000. A $2 option costs $200 per standard contract, so that cap allows at most five before fees and other limits."
  },
  "partial_sell_pct": {
    "label": "How much to sell at the first target (%)",
    "meaning": "Chooses the share of contracts to sell at the first profit target. Example: 50% of 10 contracts sells five. With three contracts, it rounds down to one. If the result is zero, all contracts follow the trailing rule after activation.",
    "effect": "Higher sells more early and leaves fewer contracts to trail. Whole-contract rounding applies.",
    "summary": "Chooses the share of contracts to sell at the first profit target.",
    "detail": "Example: 50% of 10 contracts sells five. With three contracts, it rounds down to one. If the result is zero, all contracts follow the trailing rule after activation."
  },
  "gain_pct": {
    "label": "Option gain for the first sale (%)",
    "meaning": "Sets how much the option price must rise before the first sale. Example: buying at $2 and setting 10% puts the trigger at $2.20. That is $20 profit per standard contract before costs if sold at that price. A trigger is not a guaranteed sale price.",
    "effect": "Higher waits for a larger gain; lower can take profit sooner. Reaching it is not guaranteed.",
    "summary": "Sets how much the option price must rise before the first sale.",
    "detail": "Example: buying at $2 and setting 10% puts the trigger at $2.20. That is $20 profit per standard contract before costs if sold at that price. A trigger is not a guaranteed sale price."
  },
  "partial_gain_pct": {
    "label": "Option gain for the first sale (%)",
    "meaning": "Sets how much the option price must rise before the first sale. Example: buying at $2 and setting 10% puts the trigger at $2.20. That is $20 profit per standard contract before costs if sold at that price. A trigger is not a guaranteed sale price.",
    "effect": "Higher waits for a larger gain; lower can take profit sooner. Reaching it is not guaranteed.",
    "summary": "Sets how much the option price must rise before the first sale.",
    "detail": "Example: buying at $2 and setting 10% puts the trigger at $2.20. That is $20 profit per standard contract before costs if sold at that price. A trigger is not a guaranteed sale price."
  },
  "giveback_pct": {
    "label": "Peak profit allowed back (%)",
    "meaning": "How much of the highest profit may disappear before selling. Example: 10% of $30 peak profit is $3. Selling at that threshold would keep $27 per contract before costs. This watches profit, not a 10% drop in the option’s full price. The trade’s activation rule must be met first.",
    "effect": "Higher allows a larger drop in profit; lower follows profit more tightly. This is profit percentage, not option-price percentage.",
    "summary": "How much of the highest profit may disappear before selling.",
    "detail": "Example: 10% of $30 peak profit is $3. Selling at that threshold would keep $27 per contract before costs. This watches profit, not a 10% drop in the option’s full price. The trade’s activation rule must be met first."
  },
  "legacy_giveback_pct": {
    "label": "Peak profit allowed back (%)",
    "meaning": "How much of the highest profit may disappear before selling. Example: 10% of $30 peak profit is $3. Selling at that threshold would keep $27 per contract before costs. This watches profit, not a 10% drop in the option’s full price. The trade’s activation rule must be met first.",
    "effect": "Higher allows a larger drop in profit; lower follows profit more tightly. This is profit percentage, not option-price percentage.",
    "summary": "How much of the highest profit may disappear before selling.",
    "detail": "Example: 10% of $30 peak profit is $3. Selling at that threshold would keep $27 per contract before costs. This watches profit, not a 10% drop in the option’s full price. The trade’s activation rule must be met first."
  },
  "timeframe_minutes": {
    "label": "Fail-safe candle length (minutes)",
    "meaning": "Minutes of stock prices grouped into each candle for candle safety exit. Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended.",
    "effect": "Longer candles take longer to confirm. The option-loss condition must also pass.",
    "summary": "Minutes of stock prices grouped into each candle for candle safety exit.",
    "detail": "Example: 5 means each candle covers five minutes. A candle is only complete when those five minutes have ended."
  },
  "consecutive_candles": {
    "label": "Candles in a row moving against the trade",
    "meaning": "Counts consecutive lower closes for calls or higher closes for puts. Example: call-trade closes of $100, $99, $98 and $97 contain three moves against the trade. The option must also reach the loss threshold, and this safety exit must still be active.",
    "effect": "More candles require a longer adverse sequence before an exit can trigger.",
    "summary": "Counts consecutive lower closes for calls or higher closes for puts.",
    "detail": "Example: call-trade closes of $100, $99, $98 and $97 contain three moves against the trade. The option must also reach the loss threshold, and this safety exit must still be active."
  },
  "loss_pct": {
    "label": "Option loss needed for the safety exit (%)",
    "meaning": "Requires the option’s selling quote to fall this far below entry. Example: a $2 entry with 10% loss reaches the threshold at a $1.80 bid, or $20 lost per standard contract before costs. The candle condition must also pass. The actual sale may differ.",
    "effect": "Higher tolerates a larger loss. The candle-against-the-trade condition must also pass; sale price can differ.",
    "summary": "Requires the option’s selling quote to fall this far below entry.",
    "detail": "Example: a $2 entry with 10% loss reaches the threshold at a $1.80 bid, or $20 lost per standard contract before costs. The candle condition must also pass. The actual sale may differ."
  },
  "minimum_dte": {
    "label": "Fewest days until expiration",
    "meaning": "Skips options that expire too soon. Example: 2 excludes options expiring today or tomorrow. This is days until the contract expires, not the time the bot plans to hold it.",
    "effect": "Higher excludes nearer expirations.",
    "summary": "Skips options that expire too soon.",
    "detail": "Example: 2 excludes options expiring today or tomorrow. This is days until the contract expires, not the time the bot plans to hold it."
  },
  "maximum_dte": {
    "label": "Most days until expiration",
    "meaning": "Skips options that expire too far in the future. Example: 7 excludes contracts expiring more than seven days away. This does not mean holding the trade for seven days.",
    "effect": "Lower excludes farther expirations.",
    "summary": "Skips options that expire too far in the future.",
    "detail": "Example: 7 excludes contracts expiring more than seven days away. This does not mean holding the trade for seven days."
  },
  "minimum_premium": {
    "label": "Lowest option price ($ per share)",
    "meaning": "Skips options priced below this amount. Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost.",
    "effect": "Higher excludes cheaper contracts.",
    "summary": "Skips options priced below this amount.",
    "detail": "Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost."
  },
  "maximum_premium": {
    "label": "Highest option price ($ per share)",
    "meaning": "Skips options priced above this amount. Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost.",
    "effect": "Lower excludes more expensive contracts.",
    "summary": "Skips options priced above this amount.",
    "detail": "Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost."
  },
  "maximum_spread_pct": {
    "label": "Largest gap between buying and selling quotes",
    "meaning": "Limits how far apart the option’s buy and sell quotes can be. Enter 0.08 for 8%. The ask is what sellers request; the bid is what buyers offer. Example: a $1.90 bid and $2 ask are 10 cents apart, or $10 per standard contract. The bot applies its percentage check as well as any dollar cap.",
    "effect": "Lower demands a tighter market and can leave fewer eligible contracts.",
    "summary": "Limits how far apart the option’s buy and sell quotes can be.",
    "detail": "Enter 0.08 for 8%. The ask is what sellers request; the bid is what buyers offer. Example: a $1.90 bid and $2 ask are 10 cents apart, or $10 per standard contract. The bot applies its percentage check as well as any dollar cap."
  },
  "maximum_spread_dollars": {
    "label": "Largest quote gap ($ per share)",
    "meaning": "Caps the dollar gap between the option’s buy and sell quotes. Example: a $1.90 bid and $2 ask are 10 cents apart. Enter 0.10 for that gap, equivalent to $10 per standard contract. Zero turns off this dollar cap; the percentage limit still applies.",
    "effect": "A smaller positive cap is stricter. It does not remove the separate percentage limit.",
    "summary": "Caps the dollar gap between the option’s buy and sell quotes.",
    "detail": "Example: a $1.90 bid and $2 ask are 10 cents apart. Enter 0.10 for that gap, equivalent to $10 per standard contract. Zero turns off this dollar cap; the percentage limit still applies."
  },
  "minimum_open_interest": {
    "label": "Minimum contracts already open in the market",
    "meaning": "Requires enough existing contracts in this option. Example: 100 requires at least 100 outstanding contracts, called open interest. Zero sets no minimum. This is not today’s trading volume and does not guarantee a buyer.",
    "effect": "Higher can exclude less established contracts; it does not guarantee an immediate fill.",
    "summary": "Requires enough existing contracts in this option.",
    "detail": "Example: 100 requires at least 100 outstanding contracts, called open interest. Zero sets no minimum. This is not today’s trading volume and does not guarantee a buyer."
  },
  "primary_policy": {
    "label": "How to choose the option contract",
    "meaning": "Chooses among options that passed the price and other checks. Example: “Smallest bid/ask gap” favors the narrowest difference between buying and selling quotes. “Nearest weekly expiration” favors the closest qualifying weekly date.",
    "effect": "Changing this can select a different strike or expiration; it does not remove eligibility checks.",
    "summary": "Chooses among options that passed the price and other checks.",
    "detail": "Example: “Smallest bid/ask gap” favors the narrowest difference between buying and selling quotes. “Nearest weekly expiration” favors the closest qualifying weekly date."
  },
  "target_minimum_premium": {
    "label": "Lowest preferred option price ($ per share)",
    "meaning": "Sets the lower price boundary when choosing by preferred price. Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost.",
    "effect": "Higher narrows that choice from the cheaper end.",
    "summary": "Sets the lower price boundary when choosing by preferred price.",
    "detail": "Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost."
  },
  "target_maximum_premium": {
    "label": "Highest preferred option price ($ per share)",
    "meaning": "Sets the upper price boundary when choosing by preferred price. Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost.",
    "effect": "Lower narrows that choice from the expensive end.",
    "summary": "Sets the upper price boundary when choosing by preferred price.",
    "detail": "Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost."
  },
  "target_premium": {
    "label": "Preferred option price ($ per share)",
    "meaning": "Favors options near this price when choosing by preferred price. Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost.",
    "effect": "Changing it favors contracts nearer that price within the allowed range.",
    "summary": "Favors options near this price when choosing by preferred price.",
    "detail": "Example: enter 2 for a $2 quote. One standard option contract covers 100 shares, so it costs $200 before fees. This field uses the quoted price, not the full contract cost."
  },
  "hold_minutes": {
    "label": "Time before requesting an exit (minutes)",
    "meaning": "Requests a sale after this many minutes in the trade. Example: a 30-minute limit on a 10:00 AM entry requests an exit around 10:30 AM. Safety rules or the market-close rule can exit earlier; an order may take time to fill.",
    "effect": "Lower requests an earlier exit; higher holds longer. Safety and session-close exits still apply.",
    "summary": "Requests a sale after this many minutes in the trade.",
    "detail": "Example: a 30-minute limit on a 10:00 AM entry requests an exit around 10:30 AM. Safety rules or the market-close rule can exit earlier; an order may take time to fill."
  },
  "max_hold_bars": {
    "label": "Most completed candles to hold",
    "meaning": "Limits how many candles the original exit rule can hold the trade. Example: six five-minute candles cover 30 minutes of candles. Actual elapsed time depends on entry timing and available completed candles.",
    "effect": "Higher permits a longer hold; candle length also affects elapsed time.",
    "summary": "Limits how many candles the original exit rule can hold the trade.",
    "detail": "Example: six five-minute candles cover 30 minutes of candles. Actual elapsed time depends on entry timing and available completed candles."
  },
  "missing_structure_hold_minutes": {
    "label": "Time limit when a chart level is missing (minutes)",
    "meaning": "Sets a backup exit time when the required chart level is unavailable. Example: 30 requests the fallback exit after 30 minutes held when no usable level exists. It does not create a missing stop level.",
    "effect": "Lower requests an earlier fallback exit. It does not repair missing chart data.",
    "summary": "Sets a backup exit time when the required chart level is unavailable.",
    "detail": "Example: 30 requests the fallback exit after 30 minutes held when no usable level exists. It does not create a missing stop level."
  },
  "legacy_arm_dollars": {
    "label": "Profit needed to start trailing ($ per contract)",
    "meaning": "Starts the original profit trail only after this dollar gain. Example: a $2 entry reaching a $2.65 selling quote has $65 profit per standard contract before costs. A setting of 65 starts watching for giveback at that point.",
    "effect": "Higher waits for more profit before protection starts; below it this trail does not protect the trade.",
    "summary": "Starts the original profit trail only after this dollar gain.",
    "detail": "Example: a $2 entry reaching a $2.65 selling quote has $65 profit per standard contract before costs. A setting of 65 starts watching for giveback at that point."
  },
  "final_gain_pct": {
    "label": "Option gain for the final sale (%)",
    "meaning": "Requests the last sale when the option reaches this gain. Example: a $2 entry with a 25% target reaches $2.50, or $50 gain per standard contract before costs. The final sale price may differ.",
    "effect": "Higher waits for a larger gain and can leave the trade open longer.",
    "summary": "Requests the last sale when the option reaches this gain.",
    "detail": "Example: a $2 entry with a 25% target reaches $2.50, or $50 gain per standard contract before costs. The final sale price may differ."
  },
  "reclaim_ema_period": {
    "label": "Price recovery average (candles)",
    "meaning": "How many candles set the speed of this average price line. Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles.",
    "effect": "A higher count makes the line react more slowly. A lower count makes it react faster and can change when an entry passes.",
    "summary": "How many candles set the speed of this average price line.",
    "detail": "Example: 8 uses a shorter setting than 20, so it reacts faster. This type of average, called EMA, gives newer prices more weight; it can retain influence from older candles."
  }
};
