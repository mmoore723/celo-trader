"""
log_explanations.py — Plain-English reference for every log message the bot writes
to the Live Trading audit feed (system_events table).

This module is purely additive / display-time. It does NOT touch any of the
existing log_event() call sites in trading_logic.py, risk.py, broker.py, or
database.py — it just maps message text -> a short keyword tag + layman's-terms
explanation, so the dashboard can:
  1. Show a small keyword badge next to each line in the Live Trading log feed.
  2. Let the user search/browse a full reference of every log type in the
     "Trading Log Explanations" Playbooks sub-tab.

How matching works
-------------------
`tag_for_message(msg)` walks LOG_EXPLANATIONS in order and returns the `tag`
of the first entry where ANY of its `match` substrings is found in `msg`.
Order matters: more specific patterns are listed first so a generic pattern
(like the "1m —" bar-thinking narration) can't shadow a more specific one.
"""

from typing import Optional


# Each entry:
#   tag         - short keyword shown as a badge in the Live Trading log feed
#                  and used to deep-link / search in the explanations tab
#   title       - human-friendly name of this log type
#   category    - one of: "Entries", "Exits", "Risk Gates", "Errors", "Scanning", "System"
#   match       - list of substrings; if ANY appears in the raw log message,
#                  this entry is selected (first match in list order wins)
#   explanation - plain-English description of what this log means and
#                  whether the user needs to do anything about it
LOG_EXPLANATIONS: list[dict] = [

    # ── Risk Gates — structured / high-detail ────────────────────────────────
    {
        "tag": "TRADE_BLOCKED_LOW_RR",
        "title": "Trade Blocked — Reward Too Small vs Risk",
        "category": "Risk Gates",
        "match": ["Trade_Blocked_Low_RR"],
        "explanation": (
            "The bot found a tradeable signal but skipped it because the potential "
            "reward wasn't big enough compared to the potential loss. "
            "R_R_Ratio is reward ÷ risk. Min_RR_Required is the bar it had to clear — "
            "1.2 for small/bootstrap accounts (under the balance threshold), or 1.6 "
            "once the account graduates to 'Professional Standard' (set in Settings → "
            "R:R Threshold Mode). Risk_Tier_Used shows what % of your account "
            "was being risked (e.g. Tier4_5pct = 5%). Entry_Volume_Multiplier shows "
            "how much above-normal trading volume there was (2.05 = more than double "
            "normal). Expected_Win / Expected_Loss are the dollar amounts if the trade "
            "had hit its target or stop. Trade_ID=None confirms no trade was placed."
        ),
    },
    {
        "tag": "KILL_LOCK_SET",
        "title": "Kill Lock Activated (10% Hard Cap)",
        "category": "Risk Gates",
        "match": ["KILL LOCK SET"],
        "explanation": (
            "The bot lost 10% of your account value in a single day — its absolute "
            "worst-case limit. It has now locked itself out of all trading for 24 "
            "hours (until the time shown) to stop further losses."
        ),
    },
    {
        "tag": "DAILY_LOSS_HIT",
        "title": "Daily Loss Limit Reached",
        "category": "Risk Gates",
        "match": ["DAILY LOSS LIMIT HIT: today="],
        "explanation": (
            "Confirms the bot hit its daily loss limit and won't take any more trades "
            "until the next session. 'hard_cap=True' means the stricter 10% "
            "account-wide kill lock also kicked in (24-hour freeze); "
            "'hard_cap=False' means just today's trading is paused."
        ),
    },
    {
        "tag": "DAILY_LOSS_STATUS",
        "title": "Daily Loss Limit Check-In",
        "category": "Risk Gates",
        "match": ["DAILY LOSS LIMIT: today_pnl="],
        "explanation": (
            "A status readout comparing today's running profit/loss to the daily "
            "loss threshold. By itself this doesn't mean a trade was blocked — it's "
            "just the bot reporting where it stands."
        ),
    },
    {
        "tag": "KILL_LOCK_FORCE_CLOSE",
        "title": "Emergency Shutdown — Daily Loss Cap",
        "category": "Risk Gates",
        "match": ["Daily loss limit hit — all positions closed"],
        "explanation": (
            "The bot hit its daily loss cap, immediately closed every open position, "
            "and is now frozen for 24 hours. This is the strongest safety brake — it "
            "overrides everything else."
        ),
    },

    # ── Entries ───────────────────────────────────────────────────────────────
    {
        "tag": "TRADE_ENTRY",
        "title": "Trade Entered",
        "category": "Entries",
        "match": ["ENTRY — Buying"],
        "explanation": (
            "The bot bought an options contract. The line shows the ticker, CALL or "
            "PUT, how many contracts, the price paid, which of the 8 strategies "
            "triggered it, where the stop-loss and profit target are, the "
            "reward:risk ratio, and how far above-normal the volume was."
        ),
    },
    {
        "tag": "FLIP_OVERRIDE",
        "title": "Flip Plan Overridden by Real Signal",
        "category": "Entries",
        "match": ["market structure wins, entering"],
        "explanation": (
            "After a stop-loss, the bot was primed to flip to one direction (e.g. "
            "bullish) on the next setup. But the actual signal that fired was the "
            "opposite direction. Rather than force the stale flip plan, the bot "
            "follows what the market is actually doing right now."
        ),
    },
    {
        "tag": "ORDER_SENT",
        "title": "Order Sent — Awaiting Fill",
        "category": "Entries",
        "match": ["Order sent to Alpaca"],
        "explanation": (
            "The bot submitted a buy order to Alpaca and is waiting (up to 30 "
            "seconds) for confirmation that it actually filled before recording a "
            "trade."
        ),
    },
    {
        "tag": "TRADIER_ORDER_CONFIRMED",
        "title": "Order Confirmed by Tradier",
        "category": "Entries",
        "match": ["Order confirmed by Tradier"],
        "explanation": (
            "Tradier confirmed your options order was received and processed. The "
            "order ID is shown for your records."
        ),
    },

    # ── Exits ─────────────────────────────────────────────────────────────────
    {
        "tag": "STAGE1_PROFIT",
        "title": "First Profit Target Hit (+50%)",
        "category": "Exits",
        "match": ["Took 50% profit"],
        "explanation": (
            "The trade reached its first profit milestone. The bot sold half the "
            "contracts to lock in gains, and moved the stop-loss on the remaining "
            "half to your original entry price (break-even) — so the rest of the "
            "trade can no longer lose money."
        ),
    },
    {
        "tag": "TRADE_EXIT",
        "title": "Trade Exited",
        "category": "Exits",
        "match": ["EXIT — Sold"],
        "explanation": (
            "The bot closed a position completely. Shows the ticker, option type, "
            "exit price vs. entry price, the dollar profit or loss, and why it "
            "exited — e.g. hit the profit target, hit a stop-loss, the 45-minute "
            "time limit ran out, or it was manually/emergency closed."
        ),
    },

    # ── Errors ────────────────────────────────────────────────────────────────
    {
        "tag": "PANIC_CLOSE_FAILED",
        "title": "Emergency Close Failed",
        "category": "Errors",
        "match": ["Emergency close FAILED"],
        "explanation": (
            "The bot tried to force-close all positions but the orders failed even "
            "after retrying. Open positions may still exist in your broker account — "
            "check Alpaca/Tradier directly and close manually if needed."
        ),
    },
    {
        "tag": "ORDER_TIMEOUT",
        "title": "Order Timed Out — No Fill",
        "category": "Errors",
        "match": ["Order did not fill in time"],
        "explanation": (
            "The bot placed a buy order but it didn't fill within 90 seconds, so "
            "nothing was recorded as an open trade. The bot moves on and looks for "
            "the next setup — your account wasn't charged."
        ),
    },
    {
        "tag": "ORDER_FAILED",
        "title": "Order Submission Failed",
        "category": "Errors",
        "match": ["Order submission failed"],
        "explanation": (
            "The bot tried to place an order (buy or sell) and it was rejected or "
            "hit a connection error before reaching the broker. No position was "
            "opened or closed from this attempt."
        ),
    },
    {
        "tag": "TRADIER_BAD_RESPONSE",
        "title": "Tradier Sent Back Bad Data",
        "category": "Errors",
        "match": [
            "[Tradier] Received an unreadable response",
            "returned an HTML page instead of JSON",
        ],
        "explanation": (
            "Tradier responded with something that wasn't valid JSON. There are two "
            "variants of this message: a generic 'unreadable response' usually means "
            "a one-off rate limit or server hiccup that should clear on its own. "
            "The more specific 'returned an HTML page instead of JSON — looks like a "
            "redirect to Tradier's documentation/marketing site' means the request "
            "got bounced to Tradier's docs site instead of the API — this is "
            "NOT transient and won't fix itself by retrying. It almost always means "
            "TRADIER_API_KEY is invalid/expired, or the endpoint isn't enabled for "
            "your account/plan. Check your .env TRADIER_API_KEY and TRADIER_BASE_URL. "
            "Either way, the bot returns an empty result for that call so it doesn't "
            "crash — but options data (chains, expirations, quotes) won't load until "
            "this is fixed."
        ),
    },
    {
        "tag": "TRADIER_CONN_ERROR",
        "title": "Can't Reach Tradier",
        "category": "Errors",
        "match": ["[Tradier] Connection failed"],
        "explanation": (
            "The bot couldn't connect to Tradier at all (used for options pricing "
            "and order placement). Check your internet connection and that your "
            "Tradier API key/account ID in Settings are correct."
        ),
    },
    {
        "tag": "ALPACA_CONN_ERROR",
        "title": "Can't Reach Alpaca",
        "category": "Errors",
        "match": ["[Alpaca] Connection failed"],
        "explanation": (
            "The bot couldn't connect to Alpaca (used for stock prices, account "
            "balance, and order execution). Check your internet connection and "
            "Alpaca API keys."
        ),
    },
    {
        "tag": "POSITION_MONITOR_ERROR",
        "title": "Error Monitoring Open Position",
        "category": "Errors",
        "match": ["Error while monitoring open position"],
        "explanation": (
            "The bot hit an error while checking on an open trade (e.g. a "
            "price-feed hiccup). It will try again on the next cycle — your "
            "position is still open and tracked by the broker regardless."
        ),
    },
    {
        "tag": "LOOP_ERROR",
        "title": "Unexpected Error — Bot Will Retry",
        "category": "Errors",
        "match": ["Unexpected error in trading loop"],
        "explanation": (
            "Something unexpected went wrong in the bot's main loop (a bug or an "
            "unhandled edge case). The bot catches it, logs the details, and tries "
            "again on the next cycle — it does not crash or stop running. If this "
            "repeats often, it's worth investigating."
        ),
    },
    {
        "tag": "MULTI_OPEN_TRADES",
        "title": "Multiple Open Trades Detected (Bug Flag)",
        "category": "Errors",
        "match": ["Multiple open trades detected"],
        "explanation": (
            "The bot's database shows more than one trade marked 'open' at the same "
            "time, which should never happen — only one position should be open at "
            "once. This indicates a bug; flag it for review and check your broker "
            "account for the actual open positions."
        ),
    },
    {
        "tag": "NO_OPTION_DATA",
        "title": "No Option Price Data",
        "category": "Errors",
        "match": ["Tradier (no data returned)"],
        "explanation": (
            "Tradier didn't return any usable option chain data for this ticker — "
            "this is a data/API issue, not a budget issue. Often temporary; the bot "
            "retries on the next candle."
        ),
    },

    # ── System / emergency-wide ───────────────────────────────────────────────
    {
        "tag": "PANIC_CLOSE",
        "title": "Emergency Close Triggered",
        "category": "System",
        "match": ["Emergency close triggered"],
        "explanation": (
            "All open positions were force-closed right away — either you clicked "
            "the panic/stop button or the bot triggered it automatically. No new "
            "trades will be placed until the bot is restarted."
        ),
    },
    {
        "tag": "FLIP_ARMED",
        "title": "Flip Trade Armed",
        "category": "System",
        "match": ["Flip armed — previous"],
        "explanation": (
            "The last trade was stopped out at its full stop-loss (not a "
            "partial/break-even exit). The bot is now watching for an immediate "
            "breakout in the opposite direction to re-enter — a 'flip' trade, with "
            "no cooldown."
        ),
    },
    {
        "tag": "BOT_STARTED",
        "title": "Bot Started",
        "category": "System",
        "match": ["Bot started. Account balance"],
        "explanation": (
            "The bot has started up, connected to your brokerage account, and "
            "confirmed your account balance. From here it begins scanning for "
            "setups."
        ),
    },
    {
        "tag": "PREMARKET_DATA_UNAVAILABLE",
        "title": "Pre-Market Data Not Available",
        "category": "System",
        "match": ["Pre-market data not available"],
        "explanation": (
            "Your market data plan doesn't include pre-market (before 9:30 AM ET) "
            "prices, so the bot is using regular-session data only. This is normal "
            "on free-tier plans and doesn't stop the bot from trading once the "
            "market opens."
        ),
    },
    {
        "tag": "ALREADY_IN_TRADE",
        "title": "Already In a Trade",
        "category": "System",
        "match": ["Already in a trade — monitoring current position"],
        "explanation": (
            "The bot already has a position open and is managing it (watching for "
            "profit targets, stops, and time limits). It won't open a second trade "
            "until this one closes."
        ),
    },

    # ── Risk Gates — pre-trade skip reasons ──────────────────────────────────
    {
        "tag": "KILL_LOCKED_PAUSE",
        "title": "Trading Paused — Kill Lock Active",
        "category": "Risk Gates",
        "match": ["Daily loss limit hit — trading is paused"],
        "explanation": (
            "The bot is in its 24-hour kill-lock period after hitting the daily "
            "loss cap. It's alive and checking in, but won't place any trades until "
            "the lock expires."
        ),
    },
    {
        "tag": "DAILY_LOSS_NO_MORE",
        "title": "Done Trading for Today",
        "category": "Risk Gates",
        "match": ["Daily loss limit reached. No more trades today"],
        "explanation": (
            "The bot lost as much as it's allowed to lose for the day, so it's "
            "stopped taking new trades until the next session. This caps how bad a "
            "single day can get."
        ),
    },
    {
        "tag": "LOW_BALANCE",
        "title": "Account Balance Too Low",
        "category": "Risk Gates",
        "match": ["Account balance too low to size a trade safely"],
        "explanation": (
            "Your account balance is too small for the bot to size even one "
            "contract while staying within its risk-per-trade rules. You'd need to "
            "add funds, or adjust the minimum contract cost / risk tier in Settings."
        ),
    },
    {
        "tag": "OVER_BUDGET",
        "title": "Option Too Expensive for Budget",
        "category": "Risk Gates",
        "match": ["but your budget is set to"],
        "explanation": (
            "Even the cheapest available contract for this setup costs more than "
            "your spending limit per trade. The bot skips it rather than going over "
            "budget — it'll check again next candle in case prices come down."
        ),
    },
    {
        "tag": "LIQUIDITY_FILTER",
        "title": "No Contracts Passed Quality Filters",
        "category": "Risk Gates",
        "match": ["met liquidity/spread requirements"],
        "explanation": (
            "Option contracts existed for this ticker, but none passed the bot's "
            "quality checks (bid/ask spread too wide, or open interest too low). "
            "The bot skips this setup — entering on a bad spread can eat your "
            "profit before the trade even moves."
        ),
    },
    {
        "tag": "SIZING_ZERO",
        "title": "Can't Afford Even 1 Contract Safely",
        "category": "Risk Gates",
        "match": ["if the 30% stop hits", "too expensive for current account size"],
        "explanation": (
            "This is about RISK, not the contract's price tag. If the 30% stop "
            "loss were hit, 1 contract would lose more money than your "
            "risk_per_trade budget allows — even though the premium itself "
            "(Contract premium) might be well within your max position-size cap. "
            "Risk budget = balance × risk_per_trade %. Risk per contract = "
            "(premium + 5% slippage) × 30% stop × 100. If risk-per-contract > "
            "risk budget, the bot won't size even 1 contract. Fix by raising "
            "risk_per_trade (Settings), letting the account balance grow, or "
            "waiting for a cheaper-premium setup."
        ),
    },
    {
        "tag": "LOW_RR_SKIP",
        "title": "Reward Too Small — Waiting for Better Entry",
        "category": "Risk Gates",
        "match": ["less than 1.6× the risk"],
        "explanation": (
            "The setup is real, but at the current price the potential profit doesn't "
            "clear the bot's minimum reward:risk bar (1.2 for small accounts, 1.6 for "
            "Professional Standard accounts — set in Settings → R:R Threshold Mode). "
            "It waits for a better entry rather than taking a low-quality "
            "risk/reward. (See TRADE_BLOCKED_LOW_RR for the exact numbers behind a "
            "block like this.)"
        ),
    },

    # ── Scanning ──────────────────────────────────────────────────────────────
    {
        "tag": "PREMARKET_SCAN",
        "title": "Pre-Market Scan Complete",
        "category": "Scanning",
        "match": ["Pre-market scan complete"],
        "explanation": (
            "Before the market opens, the bot scans for the day's most active "
            "stocks (highest relative volume) and builds today's watchlist — shown "
            "in the message."
        ),
    },
    {
        "tag": "WAITING_OR",
        "title": "Waiting for Opening Range",
        "category": "Scanning",
        "match": ["Waiting for the 9:30 opening candle"],
        "explanation": (
            "The market just opened and the bot is waiting for the first 5-minute "
            "candle (9:30–9:35 ET) to fully close. It needs this candle's high/low "
            "to define the 'Opening Range' that several strategies trade around."
        ),
    },
    {
        "tag": "ENTRY_ALREADY_TAKEN",
        "title": "Already Traded This Ticker Today",
        "category": "Scanning",
        "match": ["Entry already taken today. Waiting for flip setup"],
        "explanation": (
            "The bot already took its one entry on this ticker for the session. It "
            "will only trade it again if a 'flip' setup arms after a stop-loss exit."
        ),
    },
    {
        "tag": "OUTSIDE_HOURS",
        "title": "Outside Trading Hours",
        "category": "Scanning",
        "match": ["Outside trading hours. Bot is standing by"],
        "explanation": (
            "It's before/after the bot's trading window, or the market is closed "
            "(weekend/holiday). The bot is idle and will resume scanning when the "
            "window opens."
        ),
    },
    {
        "tag": "NO_SETUP",
        "title": "No Setup This Candle",
        "category": "Scanning",
        "match": ["No trade setup found on this candle"],
        "explanation": (
            "The bot checked all 8 strategies against this candle and none of them "
            "triggered. It's continuing to watch — this is the most common message "
            "you'll see."
        ),
    },
    {
        "tag": "SKIPPING_GENERIC",
        "title": "Skipping This Cycle",
        "category": "Scanning",
        "match": ["Skipping —"],
        "explanation": (
            "The bot is sitting this cycle out for the reason shown right after the "
            "dash — usually something temporary (outside trading hours, low "
            "balance, etc.) that resolves on its own."
        ),
    },

    {
        "tag": "HOLDING_POSITION",
        "title": "Position Update",
        "category": "Trade Management",
        "match": ["Holding — option @"],
        "explanation": (
            "A once-a-minute snapshot of the open position: the option's current "
            "price vs. entry, unrealised P&L, where the stop-loss currently sits, "
            "and how much time is left in the 45-minute hold window. This keeps "
            "the audit log narrating while the bot is in a trade."
        ),
    },

    # ── Catch-all — must stay LAST since "1m —" is generic ──────────────────
    {
        "tag": "BAR_THINKING",
        "title": "Bot's Minute-by-Minute Notes",
        "category": "Scanning",
        "match": [" 1m — "],
        "explanation": (
            "Running commentary on what the bot observes each minute: where price "
            "sits relative to the Opening Range, how volume compares to normal, and "
            "whether price is above or below VWAP. Most of these are just "
            "observations — the bot only acts when all the conditions for a "
            "strategy line up."
        ),
    },
]


def tag_for_message(msg: str) -> Optional[str]:
    """
    Return the keyword tag for the first LOG_EXPLANATIONS entry whose `match`
    list contains a substring found in `msg`. Returns None if nothing matches
    (the dashboard should simply omit the badge in that case).
    """
    if not msg:
        return None
    for entry in LOG_EXPLANATIONS:
        for needle in entry["match"]:
            if needle in msg:
                return entry["tag"]
    return None


def explanation_for_tag(tag: str) -> Optional[dict]:
    """Look up a LOG_EXPLANATIONS entry by its tag. Returns None if not found."""
    for entry in LOG_EXPLANATIONS:
        if entry["tag"] == tag:
            return entry
    return None
