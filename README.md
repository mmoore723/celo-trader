# celo-trader
Automated options day-trading bot

## Codebase map

### Core trading pipeline
Runs on every tick in order:

| File | Role |
|------|------|
| `trading/loop.py` | Main loop, scan scheduling, daily restart |
| `trading/entry.py` | Signal evaluation, option sizing, order execution |
| `trading/position_manager.py` | Stop management, ATR trail, exit logic |
| `trading/state.py` | Shared `LIVE_STATE` dict, Eastern Time clock |
| `trading/controls.py` | Panic close, manual exit |
| `trading/diagnostics.py` | Ghost position detection on startup |

### Strategies
Each file exports an `evaluate(today, ticker)` function that returns a `Signal` or `None`.

| File | Strategy |
|------|----------|
| `strategies/chan_break.py` | Channel trendline rejection / bounce (CHAN_BREAK) |
| `strategies/vwap_pb.py` | VWAP pullback |
| `strategies/bos_mss.py` | Break of structure / market structure shift |
| `strategies/fvg.py` | Fair value gap |
| `strategies/inst_orb.py` | Institutional opening range breakout |
| `strategies/mid_brk.py` | Midday breakout |
| `strategies/trend_cont.py` | Trend continuation |
| `strategies/aft_rev.py` | Afternoon reversal |
| `strategies/base.py` | Shared `Signal` class, `MarketStructureAnalyzer`, RVOL helpers |
| `strategy_router.py` | Runs all strategies, picks highest-confidence signal |

### Supporting logic

| File | Role |
|------|------|
| `risk.py` | Position sizing, daily loss limit, `is_trading_window()` |
| `signals.py` | VWAP bands, bar indicators fed to strategies |
| `scanner.py` | Morning scan that builds the watchlist |
| `broker.py` | Alpaca + Tradier API wrappers |
| `database.py` | SQLite reads/writes, `log_event()` |
| `config.py` | Settings, capital limits, trading windows |

### Web UI
`api/`, `dashboard/`, and `frontend/` — reads bot state, does not affect trade decisions.

---

## Strategy Playbook

This section explains every trading strategy the bot runs, written for a human reader — no jargon. Each section covers what the strategy is looking for, when it's allowed to trade, what has to be true before it fires, and what edge it's actually capturing.

---

### How the Bot Decides to Trade

Every 5 minutes during market hours, the bot runs all 8 strategies at once against the current price action. Each strategy either says "nothing interesting" or raises its hand with a signal and a confidence score between 0 and 1.

Before any trade happens, two filters run:

**Confidence floor** — A signal has to score at least 78% to be considered. Anything below that means the setup is technically present but the conditions aren't strong enough. The bot doesn't take marginal trades.

**Conflict veto** — If two strategies fire at the same time but disagree on direction (one wants a call, one wants a put) and their confidence scores are within 5 points of each other, the bot does nothing. Competing signals with similar strength mean the market is sending mixed messages.

If signals survive both filters, the highest-scoring one wins and the bot enters.

---

### 1. Opening Range Breakout Retest (INST_ORB)
**Active window:** 9:45 AM – 10:45 AM ET

**What it's looking for:**
The first 15 minutes of the trading day (9:30–9:45) establish a range — the highest price and lowest price from the open. This is called the Opening Range. Professional traders treat these levels as the day's most important reference points. A breakout above or below this range signals which direction the market is choosing for the day.

But the bot doesn't buy the breakout itself. Raw breakouts are expensive — you're buying at the top of the initial surge when everyone else is piling in. Instead, the bot waits for a *retest*.

**The three-step entry sequence:**

Step 1 — **Breakout detected.** A candle closes above the Opening Range high (bullish) or below the Opening Range low (bearish). The bot records this but does not enter.

Step 2 — **Retest.** Price pulls back toward the level it just broke. For a bullish breakout, price dips back toward the Opening Range high. The old resistance is expected to hold as support. The bot waits for the candle's low to tag within 0.15% of that level.

Step 3 — **Bounce confirmed.** After touching the level, price closes back above it (bullish) or below it (bearish). This bar is the entry. The bounce confirms the level held.

**What else has to be true:**
- Volume must be running above its normal rate (RVOL). Weak volume = fake bounce.
- Price must be on the correct side of the day's average price (VWAP) — above for calls, below for puts.
- Price must not have already run too far from the level. If it's moved more than 1.5× the average candle range past the boundary before the entry bar, it's too late — you'd be chasing.
- A 20-minute cooldown applies after each trade so the strategy can't fire repeatedly on the same setup.

**The edge:** You're entering at a level that already proved itself (held on the retest) at a much cheaper option price than the original breakout. The stop is tight — just below the level that needs to hold.

---

### 2. Break of Structure / Market Structure Shift (BOS_MSS)
**Active window:** All session (from 9:45 AM)

**What it's looking for:**
Markets move in waves — higher highs and higher lows in an uptrend, lower highs and lower lows in a downtrend. When price breaks above the most recent swing high (bullish) or below the most recent swing low (bearish), the old ceiling just became a floor. That transition is the trade.

**What has to be true:**
- Price must close beyond the last confirmed swing high or low, not just touch it.
- There must be a Fair Value Gap (a price imbalance — see strategy 4) somewhere in the last 20 bars. This acts as evidence that institutional money moved through the area.
- Volume must be at least 1.5× the normal rate. Structure breaks on weak volume are often fakeouts.
- Price must be above the 50-period average trend line (EMA50) for bullish, below for bearish.
- Price must be on the correct side of VWAP.
- If price has already run more than 1.5× the average candle range past the broken level, the bot skips it — the move already happened.
- A 20-minute cooldown applies after firing.

**The edge:** Structure breaks represent a genuine change in who controls price. The combination of volume, the trend line, and the imbalance evidence filters out fakeouts.

---

### 3. VWAP Pullback (VWAP_PB)
**Active window:** 9:45 AM – end of session

**What it's looking for:**
VWAP (Volume Weighted Average Price) is the average price all shares traded at today, weighted by how much volume traded at each price. It acts as a magnet — price tends to return to it. In a trending day, when price pulls back to VWAP and then resumes in the trend direction, that pullback is a lower-risk entry point.

**Bullish setup:**
- The 50-period trend line (EMA50) is rising — confirmed uptrend.
- VWAP is above the EMA50 — the intraday average is above the trend line.
- The previous candle's low dipped to or below VWAP (the pullback happened).
- The current candle closes back above VWAP (the bounce is confirmed).
- Volume must be above its normal rate.

**Bearish setup:** Exact mirror — EMA50 falling, VWAP below EMA50, prior candle's high tagged VWAP, current bar closes back below it.

**The edge:** You're not buying into strength — you're entering after a healthy pause in a confirmed trend, at a price level the whole market is watching. If VWAP doesn't hold, the trend is probably over, so the stop is well-defined.

---

### 4. Fair Value Gap Retest (FVG)
**Active window:** 9:45 AM – end of session

**What it's looking for:**
A Fair Value Gap is a price imbalance — a zone where price moved so fast that no trades happened in between. It shows up as a three-candle pattern: the first candle's low is higher than the third candle's high (bullish gap), or the first candle's high is lower than the third candle's low (bearish gap). The middle candle is the fast move.

These gaps act like magnets. Price often comes back to fill them. When it does, that's a defined entry with known risk: the gap has a top and a bottom, so you know exactly where the trade fails.

**What has to be true:**
- The gap must be meaningful in size — at least half the average candle range wide. Tiny gaps are noise.
- The current candle must be trading *inside* the gap (the retest is happening now).
- Volume must be at least 1.5× normal. A weak retest often means price will fall right through without reaction.
- Price must be on the correct side of VWAP.
- The bot looks back up to 20 candles for the most recent qualifying gap. Older gaps matter less.

**The edge:** The gap is a known price level with structure on both sides. When price returns to it, there's usually a reaction. The stop is just outside the gap — well-defined risk.

---

### 5. Mid-Day Breakdown (MID_BRK)
**Active window:** 10:30 AM – 1:00 PM ET | Bearish only (puts)

**What it's looking for:**
After the opening range plays out, if the market has already printed a lower high (sellers pushed back before price could make a new high) and price then collapses below the Opening Range low with VWAP acting as a ceiling above — that's a strong bearish continuation. The morning structure already flipped; the breakdown is confirmation.

**What has to be true:**
- Price must be below the Opening Range low. The range was lost, not just tested.
- Price must be below VWAP. VWAP is now acting as overhead resistance.
- The market must have already made a confirmed lower high. This proves structure shifted bearish before the entry signal.
- Volume must be at least 1.5× the average for this time of day.
- The volume rate (RVOL) must meet its threshold.

**The edge:** You're not predicting a breakdown — you're confirming one that already happened in three separate ways (lower high, range lost, VWAP overhead). Three things are already working against the bulls before the trade is placed.

---

### 6. Afternoon Reversal (AFT_REV)
**Active window:** 1:00 PM – 3:30 PM ET | Bullish only (calls)

**What it's looking for:**
After a mid-day sell-off, the market sometimes finds its footing and reverses back higher in the afternoon. This strategy looks for the first sign buyers are stepping back in — a confirmed higher low (the most recent pullback didn't go as low as the previous one) followed by a break above the most recent swing high. That sequence is the textbook start of a reversal.

**What has to be true:**
- Price must have already made a confirmed higher low — prerequisite for a reversal.
- Price must then close above the most recent swing high. This break of structure confirms buyers took control.
- Volume must be at least 1.2× the average rate. Afternoon reversals on weak volume usually fail.
- RVOL must be at least 1.0×. Afternoon volume is naturally lower, so the bar is softer — but participation still needs to be real.
- VWAP alignment is a bonus: price above VWAP at entry raises confidence, but doesn't block the trade if it's absent.

**The edge:** Most afternoon reversals fail. This strategy only fires after two structural confirmations (higher low + break above swing high), not on the first sign of hope. Waiting for both means the market has already voted on direction.

---

### 7. Trend Continuation (TREND_CONT)
**Active window:** 9:45 AM – 2:30 PM ET | Both directions

**What it's looking for:**
When a trend is already clearly established — a confirmed sequence of lower highs in a downtrend, or higher lows in an uptrend — pullbacks within that trend are re-entry opportunities. This strategy catches the second or third wave of a move rather than the first, reducing the risk of buying at a trend's turning point.

**Bearish setup:** The market is in a confirmed downtrend. The most recent lower high was printed within the last 20 candles. The current bar closes below the level of that lower high's candle — the downtrend is continuing. VWAP must be above price.

**Bullish setup:** The market is in a confirmed uptrend. The most recent higher low was within 20 candles. Current bar closes above that higher low's candle. VWAP must be below price.

**What else has to be true:**
- The pivot must be recent — within 20 candles. A pivot from an hour ago is stale and less relevant.
- RVOL must be at least 1.2×. The trend needs real participation behind it.

**The edge:** You're joining a proven trend at a discount. Direction has already been decided by the market. The freshness gate (20 candles) ensures you're not trading off a structure point that lost relevance.

---

### 8. Channel Trendline Rejection (CHAN_BREAK)
**Active window:** 9:45 AM – 12:00 PM and 1:30 PM – 2:00 PM ET | Both directions

**What it's looking for:**
When price makes a sequence of lower highs, a line drawn through those highs is a descending resistance trendline. When price makes a sequence of higher lows, a line through those is an ascending support trendline. These lines project forward, and when price approaches them, there's often a reaction.

This strategy draws the trendline from the last two swing highs (or lows), projects it to the current bar, and checks if price tagged it and then closed back through in rejection.

**Bearish (descending channel) setup:**
- The last two swing highs are both declining — a true downtrend channel.
- The channel's slope must be meaningful — nearly flat lines are excluded.
- The current candle's high must tag within 0.3% of where the trendline projects right now.
- The current candle must close below the trendline — rejection, not a breakout through it.
- Price must be below VWAP.
- The broader market structure must not be in a confirmed uptrend. Shorting a trendline tag while price is making higher highs and higher lows is counter-trend and loses.
- Channel pivots can't be older than 40 candles. Old channels have lost their authority.

**Bullish (ascending channel) setup:** Mirror logic — two rising swing lows, projected trendline, bar low tags within 0.3%, close is above the line (bounce off support), price above VWAP. Blocked in confirmed downtrends.

**What else has to be true:**
- RVOL must be at least 1.0×. A trendline touch with weak volume is noise, not a signal.
- The 12:00–1:30 PM window is excluded. Mid-day trendline touches produce fake bounces because there's no real participation behind them.

**The edge:** Trendlines are predictable reaction zones that market participants actively watch. When price touches and rejects cleanly with real volume, and the broader trend isn't fighting your direction, it's the highest-probability moment to trade the rejection.

---

### Trade Management

Every trade is managed the same way regardless of which strategy triggered.

**Sizing:** The number of contracts is calculated using a risk ladder based on account size. At a small account (under $5k), the bot risks 5% per trade to compound faster. As the account grows, risk per trade scales down automatically — 3% from $5k to $25k, 2% from $25k to $50k, 1% above $50k. Sizing is baked into the math and isn't optional.

**Stop loss:** Set at 20% below the option's entry price. Tightens automatically every 15 minutes — dropping to 15% at the 15-minute mark and flooring at 10% after 30 minutes. This protects profits from theta decay (options lose value over time) by getting tighter the longer the trade runs.

**Stage 1 exit:** When the option gains 50%, half the position is sold. This locks in a profit on half the contracts and takes risk off the table.

**Stage 2 exit:** The remaining half runs until one of three things happens: (a) the option drops back to entry × 1.15 — the runner locks in at least 15% profit before exit, or (b) the time limit is hit.

**Early momentum stop:** If the trade is down more than 12% within the first 30 minutes, it's closed immediately. Fast losses on a fresh trade mean the setup didn't work — holding burns time value for nothing.

**Time limits:** Trades that haven't hit Stage 1 are closed after 30 minutes. Trades that already hit Stage 1 are allowed to run up to 90 minutes.

**End of day:** All open positions are closed by 3:55 PM ET, no exceptions.

---

### Risk Controls

**Daily loss cap:** If the account loses 10% in a single day, all trading stops and the bot locks itself for 24 hours.

**Conflict veto:** Competing signals with similar confidence (within 5 points) and opposite directions cancel each other out. Mixed signals = no trade.

**Confidence floor:** No signal below 78% is acted on, regardless of which strategy generated it.

**Cooldown windows:** INST_ORB and BOS_MSS both enforce a 20-minute cooldown after firing. This prevents re-entering the same setup repeatedly if the first entry fails.

**Position limit:** The bot tracks a maximum of 2 open positions at once. New signals wait until a slot frees up.

---

## Deployment

Build frontend on Mac (EC2 ARM64 cannot build):
```bash
cd frontend && npm run build
cd .. && git add frontend/dist/ && git commit -m "Rebuild dist" && git push
```

Deploy to EC2:
```bash
cd /opt/celo_trader && git pull && sudo systemctl restart celo-dashboard
```
