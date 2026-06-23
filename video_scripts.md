# Strategy Walkthrough Video Scripts

Eight short (3–5 min) screen-recorded walkthroughs, one per strategy. Each is written to be recorded over the new Playbooks page — open the relevant tab, use the real-example step-through slider as the script calls for it. Read naturally, don't read word-for-word; this is a speaking outline, not a teleprompter script.

General intro (record once, use as the channel/series intro or cut into video 1):

> "This bot runs eight different setups, and instead of just telling you the rules, I'm going to show you each one happening on a real chart, from a real trading day — not a made-up example. Let's go through them one at a time."

---

## 1. INST_ORB — Institutional Opening Range Breakout

**Hook:** "This is the highest-confidence setup the bot has — it fires earliest in the day, and it's the simplest to understand."

**Concept:** The first 5 minutes of trading sets a range — a high and a low. That range is the "opening range." When price closes convincingly above that high on big volume, it usually means institutions are buying the breakout, not just retail noise. Below the low with the same conditions is the bearish version.

**Walk the chart:** Pull up a real example. Point at the opening range box on the chart. "Watch what happens here — price pushes above the top of that box." Step the slider forward one notch at a time. "And look at the volume bar underneath — it has to cross this gate line. Double normal volume. If it doesn't, the bot does not enter, no matter how good the price move looks."

**The gates, spoken plainly:** Only fires in the first hour. Needs price above VWAP for a call, below for a put. Volume has to be at least double normal.

**Common mistake to flag:** "A lot of people would enter the second price pokes above that high. The bot waits for the candle to actually close above it, with the volume already confirmed — that patience is most of the edge."

**Close:** "This is also the only setup with a 'flip' — if it gets stopped out, the bot will immediately check if the other side of the range is breaking instead. We'll cover that risk rule in the settings video."

---

## 2. BOS_MSS — Break of Structure / Market Structure Shift

**Hook:** "If ORB is the opening bell, this is what happens once a real trend gets going."

**Concept:** Markets move in zig-zags — higher highs and higher lows in an uptrend, lower highs and lower lows in a downtrend. A "break of structure" is when price takes out the most recent swing low (in a downtrend) — confirming the move is real, not just a pullback.

**Walk the chart:** "See these labels — SH, LH, SL? The bot is tracking the zig-zag in real time. Watch this candle right here — it breaks below the SL level. That's the trigger." Step through slowly on this one since the structure-tracking is the hard part to see.

**Common mistake:** "The label itself isn't the entry — people see 'LL' marked and think that's the signal. It's not. The entry is the bar that closes BELOW that level, one bar later."

**Close:** "Second highest confidence in the whole system, because by the time this fires, the trend has already proven itself."

---

## 3. VWAP_PB — VWAP Pullback

**Hook:** "This one's about buying value, not chasing momentum."

**Concept:** VWAP is the average price everyone's paid today, weighted by how much volume traded at each price. Institutions treat it like a fair-value line — buy below it, sell above it. In an uptrend, when price dips back down to touch VWAP and bounces, that's the institutional buy zone.

**Walk the chart:** "Watch the price come down and just kiss this VWAP line — see how it doesn't close through it, just touches and bounces? That's the setup. If it had closed clean through the line, this trade doesn't happen."

**Pro tip to mention:** "The best version of this is the SECOND time price tests VWAP after trending — not the first."

**Close:** "Lower drama than the breakout trades, but a real statistical edge — you're buying where the volume-weighted crowd already agrees is fair value."

---

## 4. FVG — Fair Value Gap

**Hook:** "Think of this like a pothole in the road that price has to come back and fill."

**Concept:** Sometimes price moves so fast it leaves a gap — a three-candle pattern where candle 3's low is above candle 1's high. That gap never got properly traded through. Price has a tendency to come back and fill it before continuing.

**Walk the chart:** "Here's the gap — this empty space between these two candles. Price runs away, then comes back. Watch it enter the zone right here — that's the entry, not when it first left."

**Close:** "The bot doesn't chase price away from the gap. It waits for the gap to get revisited — that patience is the whole strategy."

---

## 5. MID_BRK — Midday Breakdown

**Hook:** "This is a second-leg trade — using what already happened in the morning to set up an afternoon move."

**Concept:** Midday (11:00am–1:30pm) often just drifts. But if the morning already established a clear downtrend with a confirmed lower high, and price finally breaks the opening range low during this window, that's a continuation — not a new idea, a second leg of the same idea.

**Walk the chart:** "See this stair-step down in the morning — that's the trend. Then midday, price just sits near this red line — the opening range low — and finally breaks it with a volume spike. That's the trigger."

**Common mistake:** "Without that morning trend already confirmed, this setup doesn't fire at all — midday traps without a pre-existing trend are exactly what this gate is designed to avoid."

---

## 6. AFT_REV — Afternoon Reversal

**Hook:** "Institutions reposition in the afternoon — this catches them doing it."

**Concept:** After a morning downtrend, sellers eventually run out of steam, shown by a "higher low" forming. When price then breaks above the most recent lower high, the downtrend structure is broken — a reversal is underway.

**Walk the chart:** "Here's the higher low forming — first sign sellers are tired. Now watch price break above this resistance level, the last lower high. That break, not the higher low itself, is the entry."

**Close:** "The bot doesn't guess the reversal is coming — it waits for proof, the actual break, before it commits."

---

## 7. TREND_CONT — Trend Continuation

**Hook:** "This is the professional move — re-entering a trend instead of chasing the first one."

**Concept:** Once a trend is established, the smart re-entry is on a pullback, not the initial breakout everyone already saw. In a downtrend, price pulls back to form a lower high, then resumes lower — the bot enters when that pullback fails.

**Walk the chart:** "This is a pullback candle — see it forming a lower high here? Now watch the rejection candle right after — that's the entry trigger, the bar after it closes."

**Worth mentioning:** "This is the only setup with a lower volume requirement, because the trend's already proven — you need less new participation to keep an existing move going."

---

## 8. CHAN_BREAK — Channel Trendline Rejection

**Hook:** "This is the most precise setup in the whole system — and the highest confidence ceiling."

**Concept:** When price makes two or more lower highs, you can draw a trendline through them — a descending channel. That line becomes resistance. Every time price taps it and gets rejected, that's a short opportunity.

**Walk the chart:** "Watch this descending line the bot's projecting forward. Price comes up, tags it — see the wick poking through but the body closing back under? That's a clean rejection, that's the entry."

**Close:** "Highest confidence ceiling of any strategy here, because by the time price has rejected this same line two or three times, the pattern is about as proven as it gets intraday."

---

## Production notes for whoever's recording

- Use the real chart on each Playbooks tab — the step-through slider lets you reveal the setup one candle at a time as you talk, which is the whole point of building it that way.
- If a strategy's tab shows "no real example yet" (MID_BRK and AFT_REV, as of this writing — they haven't fired in a real session yet), say so on camera rather than skipping it: "this one hasn't fired live yet, so I'll walk through the rule on the text card instead, and we'll add the real chart once it does." That's more credible than dead air or pretending there's a chart when there isn't.
- Keep each video under 5 minutes — this audience skims, and a tight video gets rewatched more than a thorough one.
