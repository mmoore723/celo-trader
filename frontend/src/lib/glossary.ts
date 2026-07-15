/**
 * glossary.ts — Single source of truth for all trading term definitions.
 * Imported by Tooltip usage across Daily Brief, Playbooks, and Performance.
 */
export const GLOSSARY: Record<string, string> = {
  // ── Market / scanner terms ──────────────────────────────────────────────────
  RVOL:
    "Relative Volume: today's trading volume compared to the historical average for this exact time of day. " +
    "2× means twice the usual activity. Higher RVOL = more institutions involved = the move is more likely real, not a fake-out.",

  ATR:
    "Average True Range (14-day): measures how much the stock typically moves per day. " +
    "A $1 ATR means it swings about $1 on an average day. Higher ATR = bigger option premium swings = more profit potential (and more risk).",

  "ATR%":
    "ATR expressed as a percentage of the stock's price. " +
    "Useful for comparing volatility across stocks at different price levels — e.g. a $2 ATR on a $200 stock is 1%, the same volatility as a $0.50 ATR on a $50 stock.",

  "Gap%":
    "Pre-market gap: how much the stock's pre-market price differs from yesterday's close. " +
    "A 2% gap up means the stock is trading 2% higher before the market opens. Larger gaps signal stronger directional conviction and better ORB setups.",

  Grade:
    "Setup quality grade based on gap size, RVOL, and ATR. " +
    "A+ = all three strong (best setups). A = solid. B = moderate. C = weak gap only. Watch = no gap or volume — monitor but don't force it.",

  Direction:
    "Bot's pre-market directional bias. " +
    "CALLS = bullish lean based on gap direction and momentum. PUTS = bearish lean. NEUTRAL = no clear edge pre-market.",

  // ── Options / trade terms ───────────────────────────────────────────────────
  ORB:
    "Opening Range Breakout: the price range (high and low) formed during 9:30–9:44 ET. " +
    "A breakout above the ORB high with volume triggers a call entry; a breakdown below the ORB low triggers a put entry.",

  VWAP:
    "Volume Weighted Average Price: the average price weighted by how much volume traded at each price level throughout the day. " +
    "Acts as a key support/resistance line — institutions often use VWAP as a benchmark.",

  "Stage 1":
    "First profit target: when option premium gains 50% from the entry price, half the position is sold to lock in profit. " +
    "Stage 2 then activates an ATR trailing stop on the remaining contracts.",

  "ATR Trail":
    "A trailing stop that uses the 5-minute ATR to dynamically set a floor under your gains. " +
    "It only activates after Stage 1 hits AND 5 minutes have passed. Designed to let winners run while protecting the profit already made.",

  // ── Performance terms ───────────────────────────────────────────────────────
  "Win Rate":
    "Percentage of closed trades that ended in profit. " +
    "50%+ is solid, but win rate alone doesn't tell the full story — a 40% win rate can still be profitable if average wins are much larger than average losses.",

  "Profit Factor":
    "Total gross profit ÷ total gross losses (dollar amounts). " +
    "Above 1.0 = profitable overall. Above 1.5 = good edge. Above 2.0 = strong edge. Below 1.0 = losing money overall.",

  MFE:
    "Maximum Favorable Excursion: the best (highest) point the trade reached before it closed. " +
    "If your MFE is much higher than your exit price, it means the trade was a winner at some point but gave back gains before exiting — a sign exits may need tightening.",

  MAE:
    "Maximum Adverse Excursion: the worst (lowest) point the trade hit before recovering. " +
    "High MAE with a profitable exit means the trade was scary but recovered. Very high MAE on losers means stops may be too wide.",

  "Exit Efficiency":
    "How much of the available gain you actually captured, as a percentage. " +
    "If a trade peaked at +100% and you exited at +60%, your exit efficiency is 60%. Higher is better — low efficiency means leaving money on the table.",
};
