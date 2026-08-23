import { useEffect, useRef, useState } from "react";
import {
  Check, ChevronLeft, ChevronRight, Play, ShieldCheck,
} from "lucide-react";
import type { ReviewedStrategyCatalogEntry } from "../../lib/api";

export type LessonId = "v2_orb" | "v2_trend" | "v2_spy_fvg" | "v2_two_leg" | "v2_recovery";
type LessonStep = {
  label: string;
  title: string;
  lesson: string;
  coach: string;
  watch: string[];
  avoid: string;
  chartFocus: number;
  question: string;
  answers: string[];
  correct: number;
  answerWhy: string;
};
type Course = {
  id: LessonId;
  title: string;
  shortTitle: string;
  level: string;
  description: string;
  steps: LessonStep[];
};

const STRATEGY_ID_BY_LESSON: Record<LessonId, string> = {
  v2_orb: "V2_ORB_PULLBACK",
  v2_trend: "V2_SPY_TREND_CONT",
  v2_spy_fvg: "V2_SPY_AFTERNOON_FVG",
  v2_two_leg: "V2_TSLA_TWO_LEG_TREND_PULLBACK",
  v2_recovery: "V2_FAILED_OR_BREAK_VWAP_REVERSION",
};

const EVIDENCE_LABELS: Record<ReviewedStrategyCatalogEntry["evidence_grade"], { label: string; detail: string; color: string; background: string }> = {
  passed_declared_holdout: {
    label: "Passed later-data check",
    detail: "The rule was chosen on earlier data and remained positive on the predeclared later period.",
    color: "#137a46",
    background: "#eaf8f0",
  },
  promising_underpowered: {
    label: "Promising · small sample",
    detail: "The paid-quote results were positive, but the study finished below its predeclared sample requirement.",
    color: "#9a5b00",
    background: "#fff6df",
  },
  promising_inconsistent: {
    label: "Promising · inconsistent months",
    detail: "The aggregate paid-quote result was positive, but performance was not stable across the measured months.",
    color: "#9a5b00",
    background: "#fff6df",
  },
};

const COACH_IMAGE = "/images/coach-celo-v5.png?v=1";

const COURSES: Course[] = [
  {
    id: "v2_orb",
    title: "TSLA Opening-Range Pullback",
    shortTitle: "Opening-Range Pullback",
    level: "Beginner · 5 steps",
    description: "A patient setup: let price break the opening range, pull back, and prove it can continue.",
    steps: [
      { label: "Range", title: "First, draw the morning map", lesson: "From 9:30 to 9:45 ET, we do not trade. We mark the high and low from the first three five-minute candles. That is the opening range.", coach: "No guessing yet. We are just drawing the two boundaries that matter.", watch: ["The high of the first 15 minutes", "The low of the first 15 minutes", "A finished 5-minute candle"], avoid: "Fast opening candles can be noisy. No trade happens while the range is being built.", chartFocus: 0, question: "What is the job during the first 15 minutes?", answers: ["Buy the first strong candle", "Mark the range and wait", "Guess the day’s direction"], correct: 1, answerWhy: "Right. The range gives the trade a clear map before we risk anything." },
      { label: "Break", title: "A break gets attention — not an entry", lesson: "After 9:45, price must close outside the opening range. A quick wick through the line does not count.", coach: "The close is proof that price pushed through the boundary. But we still do not chase it.", watch: ["A completed candle outside the range", "The direction of the break", "A break before 10:30 ET"], avoid: "One fast poke outside the range can snap right back. A close matters more than excitement.", chartFocus: 1, question: "Price closes above the range. What is the disciplined move?", answers: ["Buy a call immediately", "Wait for the pullback", "Ignore every breakout"], correct: 1, answerWhy: "Right. This is a pullback strategy. We let price come back to the level instead of chasing." },
      { label: "Pullback", title: "Let price come back to the level", lesson: "For a bullish setup, price revisits the broken range high. For a bearish setup, it revisits the broken range low. This is the no-chase moment.", coach: "Patience is protection. If price never comes back, we let it go.", watch: ["The first revisit of the broken level", "Whether the level holds", "The pullback high or low"], avoid: "If price cuts through the whole range, the setup is damaged. We do not force it.", chartFocus: 2, question: "The pullback touches the level but has not bounced. What now?", answers: ["Enter now", "Wait for proof", "Add extra contracts"], correct: 1, answerWhy: "Right. A touch is not a bounce. The next candle must prove price reclaimed the level." },
      { label: "Confirm", title: "Enter only after proof", lesson: "For a bullish trade, price must reclaim the range level, beat the prior candle, and be above VWAP. For a bearish trade, the reverse must be true.", coach: "Three checks keep us out of the messy back-and-forth stuff we call chop.", watch: ["Close back beyond the range", "Break of the prior candle in the trade direction", "Correct side of VWAP"], avoid: "If price keeps crossing VWAP or the range boundary, that is chop. The correct trade is no trade.", chartFocus: 3, question: "Which sign best separates confirmation from chop?", answers: ["A cheap option premium", "Price holds beyond the level and VWAP", "A social-media alert"], correct: 1, answerWhy: "Right. The chart structure must do the convincing — not a cheap contract or a headline." },
      { label: "Protect", title: "Protect the account when the idea is wrong", lesson: "Every trade has an invalidation line: the pullback low for a bullish trade or the pullback high for a bearish trade. If price reaches it, the original idea did not work.", coach: "Exiting by a rule is a win for discipline. We protect the account so it can trade another day.", watch: ["The pullback invalidation level", "Whether price still holds its VWAP side", "The paper bot’s account-wide exits"], avoid: "Never widen a stop or add contracts to rescue a losing idea.", chartFocus: 4, question: "Price loses the pullback low on a bullish trade. What does that mean?", answers: ["Exit by the rule", "Buy more to average down", "Wait forever"], correct: 0, answerWhy: "Right. The setup is invalid. A small planned loss is far safer than turning one trade into a gamble." },
    ],
  },
  {
    id: "v2_trend",
    title: "SPY Trend Continuation",
    shortTitle: "Trend Continuation",
    level: "Intermediate · 5 steps",
    description: "A SPY trend needs structure, a pause, and proof that momentum has resumed before an entry is considered.",
    steps: [
      { label: "Trend", title: "Start with a real trend", lesson: "The quick trend line must be above the slower line for a call idea, or below it for a put idea. Price needs to be holding that same side.", coach: "A flat or crossed chart is not a trend. It is a wait.", watch: ["Both trend lines pointing together", "Price holding the same side", "Finished 5-minute candles"], avoid: "Crossing, flat lines are chop. We do not predict which way they will break.", chartFocus: 0, question: "What makes a trend usable?", answers: ["Lines pointing the same way", "The biggest candle", "The cheapest option"], correct: 0, answerWhy: "Right. The direction has to agree before a continuation setup can make sense." },
      { label: "Pause", title: "Let the trend breathe", lesson: "A healthy trend often pauses or pulls back. We want a controlled pause, not a collapse through the structure.", coach: "The pause gives the next move room to prove itself. We do not buy the middle of a burst.", watch: ["A shallow pullback", "Structure still holding", "Price not losing its trend side"], avoid: "A sharp reversal is not a pause. Do not call it one because you want a trade.", chartFocus: 1, question: "What do we wait for after a strong trend move?", answers: ["A controlled pause", "More random candles", "A larger position"], correct: 0, answerWhy: "Right. The pause is where the bot looks for a safer continuation opportunity." },
      { label: "Resume", title: "Wait for momentum to resume", lesson: "The completed signal candle must close through its recent mini-range in the direction of the trend.", coach: "We want the next push to show up on a finished candle—not halfway through one.", watch: ["Close beyond the mini-range", "Trend direction still intact", "Reasonable option spread"], avoid: "Do not enter while a candle is still forming. It can look strong and finish weak.", chartFocus: 2, question: "Why wait for the candle to finish?", answers: ["It gives the rule a completed fact", "It guarantees a winner", "It makes the option cheaper"], correct: 0, answerWhy: "Right. A completed candle gives the bot a real, repeatable signal instead of a moving target." },
      { label: "Confirm", title: "Enter with the trend, not against it", lesson: "When structure, direction, and the completed signal agree, the bot checks the next available option quote. Observation records the decision without an order; an enabled strategy can send the order.", coach: "This is a simple rule: the chart gives the direction first, then the option is chosen.", watch: ["Structure and signal agree", "The next available quote", "A spread the account can handle"], avoid: "The bot never looks at a future candle to make an entry look smarter.", chartFocus: 3, question: "Which comes first: the option or the chart signal?", answers: ["The chart signal", "The option premium", "A prediction"], correct: 0, answerWhy: "Right. The chart creates the idea. The option is selected afterward to express it." },
      { label: "Protect", title: "Risk rules protect the trend trade too", lesson: "An invalidation level sits beyond the signal structure. If that structure breaks, the trend idea did not hold and the bot follows its exit rules.", coach: "A trade needs an exit before it needs hope. The same account safety rules protect every strategy.", watch: ["The structural invalidation", "VWAP and momentum changes", "The account-wide guardrails"], avoid: "Do not add contracts because a trend trade is losing.", chartFocus: 4, question: "What should happen when trend structure fails?", answers: ["Exit by the rule", "Double the position", "Move the stop farther away"], correct: 0, answerWhy: "Right. We limit the loss when the original trend story stops being true." },
    ],
  },
  {
    id: "v2_spy_fvg",
    title: "SPY Afternoon Fair Value Gap",
    shortTitle: "Afternoon Fair Value Gap",
    level: "Intermediate · 5 steps",
    description: "A narrow afternoon SPY setup: identify an imbalance, wait for its first return, then demand trend and VWAP agreement.",
    steps: [
      { label: "Window", title: "Start only in the afternoon window", lesson: "This rule watches SPY only from 1:30 to 3:00 PM Eastern. Outside that window, it does nothing.", coach: "A good setup at the wrong time is not this setup. The clock is part of the rule.", watch: ["SPY only", "1:30 to 3:00 PM ET", "Completed 5-minute candles"], avoid: "Do not turn every all-day gap into a trade. This version was tested only in its afternoon window.", chartFocus: 0, question: "When can this particular rule look for a trade?", answers: ["All day", "Only from 1:30–3:00 PM ET", "Before the open"], correct: 1, answerWhy: "Right. Keeping the tested time window prevents the bot from silently changing the strategy." },
      { label: "Gap", title: "Find a real three-candle imbalance", lesson: "An upward gap exists when the first candle’s high is below the third candle’s low. A downward gap is the mirror image. The gap must be large enough compared with ATR.", coach: "We are looking for a space price moved through quickly—not a tiny ordinary wiggle.", watch: ["Three completed candles", "A gap at least half an ATR wide", "Direction of the gap"], avoid: "A tiny gap is often ordinary noise. It does not qualify just because we can draw a box around it.", chartFocus: 1, question: "What makes this more than a random tiny gap?", answers: ["It is at least 0.5 × ATR", "It has a green candle", "The option is cheap"], correct: 0, answerWhy: "Right. The size test makes the imbalance meaningful relative to current movement." },
      { label: "Return", title: "Wait for the first return", lesson: "After the gap forms, price must come back and overlap its zone for the first time. The retest candle needs to close on the favorable half of that zone.", coach: "We do not chase the move that made the gap. We wait for price to revisit the area and show it can hold.", watch: ["First revisit only", "Price overlaps the zone", "Close on the favorable half"], avoid: "If price has already revisited the zone, the opportunity is used. We do not keep taking the same gap again.", chartFocus: 2, question: "What does the bot wait for after the gap forms?", answers: ["The first return to the gap", "Any later bounce", "A prediction"], correct: 0, answerWhy: "Right. The first retest is the specific condition measured in the study." },
      { label: "Align", title: "Let VWAP and trend agree", lesson: "For a call idea, the fast EMA is above the slow EMA and price is above VWAP. For a put idea, both relationships reverse.", coach: "The gap tells us where to look. Trend and VWAP tell us whether the direction is supported.", watch: ["EMA 8 versus EMA 20", "Correct side of session VWAP", "A completed retest candle"], avoid: "If VWAP and trend disagree, we do not argue with the chart. The setup is skipped.", chartFocus: 3, question: "What must agree before this rule can enter?", answers: ["Gap, EMA trend, and VWAP", "A headline and a hunch", "Only RSI"], correct: 0, answerWhy: "Right. This is a confluence rule, not a one-indicator trade." },
      { label: "Exit", title: "Use the predeclared 30-minute exit", lesson: "After the completed five-minute signal, entry uses the next one-minute option ask. The same contract exits 30 minutes later at its observed bid.", coach: "The exit is fixed so we can judge the entry honestly. We do not rewrite it after seeing a good or bad outcome.", watch: ["Next one-minute option ask", "Same contract", "Observed bid 30 minutes later"], avoid: "Do not pretend the bot received the candle-close price or the best price later in the move.", chartFocus: 4, question: "How is the option exit measured?", answers: ["Same contract’s bid 30 minutes later", "The day’s best option price", "Tomorrow morning"], correct: 0, answerWhy: "Right. The measurement uses a repeatable, real bid/ask convention." },
    ],
  },
  {
    id: "v2_two_leg",
    title: "TSLA Two-Leg Trend Pullback",
    shortTitle: "Two-Leg Trend Pullback",
    level: "Intermediate · 5 steps",
    description: "A one-minute TSLA continuation setup: one impulse leg, one controlled pullback leg, then a completed reclaim.",
    steps: [
      { label: "Trend", title: "Begin with aligned trend structure", lesson: "Price, VWAP, and the fast and slow EMAs must point in the same direction before a pullback is considered.", coach: "The trend earns our attention first. Without alignment, there is no continuation trade.", watch: ["Price on the trend side of VWAP", "Fast EMA leading slow EMA", "Completed one-minute bars"], avoid: "Flat or repeatedly crossing lines are chop, not a clean trend.", chartFocus: 0, question: "What must exist before looking for the impulse and pullback?", answers: ["Aligned trend structure", "A cheap option", "Any large candle"], correct: 0, answerWhy: "Right. This is a continuation setup, so the trend comes first." },
      { label: "Impulse", title: "Wait for a meaningful first leg", lesson: "After 9:45 ET, TSLA must move at least one ATR away from its 9:45 reference while price stays above VWAP with EMA 9 above EMA 20 for a call. The relationships reverse for a put.", coach: "This impulse is leg one. It proves the trend moved far enough to deserve a pullback watch.", watch: ["At least a one-ATR move", "VWAP holds", "EMA 9 leads EMA 20"], avoid: "A small drift is not the tested impulse, even if it points in the right direction.", chartFocus: 1, question: "What makes the first leg meaningful?", answers: ["At least one ATR with alignment", "Any green candle", "A cheap contract"], correct: 0, answerWhy: "Right. Distance and trend alignment define the first leg." },
      { label: "Pullback", title: "Let one controlled pullback form", lesson: "The second leg is a 0.25–1.25 ATR pullback toward EMA 9. It must remain on the correct side of VWAP and cannot break the EMA trend.", coach: "The pullback gives us location. It is not an entry by itself.", watch: ["Pullback reaches EMA 9", "Retrace stays within 0.25–1.25 ATR", "VWAP and EMA structure remain intact"], avoid: "A close through VWAP or an EMA cross cancels the setup.", chartFocus: 2, question: "Is the pullback touch the entry?", answers: ["No, wait for reclaim", "Yes, immediately", "Only after a headline"], correct: 0, answerWhy: "Right. The completed reclaim—not the touch—creates the entry decision." },
      { label: "Reclaim", title: "Enter only when momentum resumes", lesson: "The completed one-minute candle must close beyond the prior candle in the original trend direction and back beyond EMA 9. The next minute's selected option ask is the entry reference.", coach: "Leg one shows force. Leg two tests it. The reclaim provides proof.", watch: ["Completed one-minute reclaim", "Original trend direction", "Next-minute option ask"], avoid: "Do not enter on the forming reclaim candle or borrow a later better price.", chartFocus: 3, question: "What triggers the entry decision?", answers: ["A completed reclaim candle", "The pullback touch", "A prediction"], correct: 0, answerWhy: "Right. The next available option ask follows completed chart proof." },
      { label: "Protect", title: "Use the tested 90-minute plan", lesson: "Entry uses the next available option ask and the same contract is evaluated at its observed bid 90 minutes later, subject to account-wide protection.", coach: "The same entry and exit convention used in testing keeps live paper evidence honest.", watch: ["Next available option ask", "Same contract", "Observed bid after 90 minutes"], avoid: "Do not substitute a candle close or the best later price for an executable option quote.", chartFocus: 4, question: "How is this tested trade measured?", answers: ["Next ask and same-contract 90-minute bid", "Best price of the day", "Underlying close only"], correct: 0, answerWhy: "Right. Real bid/ask timing prevents imaginary fills." },
    ],
  },
  {
    id: "v2_recovery",
    title: "SPY Failed-Range Recovery",
    shortTitle: "Failed-Range Recovery",
    level: "Intermediate · 5 steps",
    description: "A failed opening-range breakout reverses only after a completed candle proves price returned inside the range with room to VWAP.",
    steps: [
      { label: "Range", title: "Build the opening-range map", lesson: "Use the completed one-minute bars from 9:30 through 9:44 ET to mark SPY's opening-range high and low. No entry is allowed while that range is forming.", coach: "The two range boundaries tell us where a breakout can succeed—or fail.", watch: ["9:30–9:44 ET completed bars", "Opening-range high and low", "No trade while the range forms"], avoid: "Do not move the boundaries after later candles appear.", chartFocus: 0, question: "When is the opening range complete?", answers: ["At 9:45 ET", "At noon", "After a trade"], correct: 0, answerWhy: "Right. The range is fixed before the strategy evaluates a failed break." },
      { label: "Break", title: "Require a meaningful break", lesson: "Before 11:00 ET, a completed one-minute close must travel at least 5% of the opening-range width beyond the high or low.", coach: "A wick is not enough. The candle must finish outside by the measured amount.", watch: ["Completed one-minute close", "At least 0.05 × range outside", "Break no later than 11:00 ET"], avoid: "A tiny poke or unfinished candle is not a qualifying breakout.", chartFocus: 1, question: "What qualifies the breakout?", answers: ["A completed close beyond the threshold", "Any wick", "A cheap option"], correct: 0, answerWhy: "Right. The completed close makes the condition causal and repeatable." },
      { label: "Fail", title: "Wait for the breakout to fail", lesson: "By noon, an opposite-color completed candle must close back inside the opening range. That reversal—not the original breakout—is the trade direction.", coach: "The market tried one direction and could not hold it. We wait for proof before considering the other side.", watch: ["Opposite-color candle", "Close back inside the range", "Failure by 12:00 ET"], avoid: "Do not predict a failure while price is still outside the range.", chartFocus: 2, question: "An upside break fails back inside. Which idea is evaluated?", answers: ["A put idea", "A call idea", "Both at once"], correct: 0, answerWhy: "Right. The failed upside break produces a bearish reversal idea." },
      { label: "Room", title: "Demand room to VWAP", lesson: "The recovery candle must still have at least 5% of the opening-range width available before session VWAP. This avoids entering after the reversal has already reached its nearby destination.", coach: "VWAP is a destination check here—not a magic signal by itself.", watch: ["Session VWAP", "At least 0.05 × range of room", "Stop beyond the failed-break extreme"], avoid: "Skip the setup if price has already crowded into VWAP.", chartFocus: 3, question: "Why measure room to VWAP?", answers: ["To avoid a late entry with no room", "To guarantee profit", "To pick the cheapest strike"], correct: 0, answerWhy: "Right. It filters reversals whose nearby opportunity may already be spent." },
      { label: "Execute", title: "Select the option only after chart proof", lesson: "After the completed failure candle, the contract selector chooses a 7–21 DTE SPY call or put. The order intent records the exact OCC contract, working limit, maximum allowed price, quantity, and 30-minute exit before the broker is asked to fill it.", coach: "The chart creates the direction. Then the option and price plan express that exact idea.", watch: ["Next-minute contract quote", "Exact strike and expiration", "Working limit, price ceiling, quantity, and 30-minute exit"], avoid: "Do not confuse the maximum allowed price with the intended entry limit, and do not substitute another contract after entry.", chartFocus: 4, question: "When is the strike selected?", answers: ["After the chart signal qualifies", "Before the range forms", "After the exit"], correct: 0, answerWhy: "Right. Contract selection is part of execution, not a standalone prediction." },
    ],
  },
];

const GUARDRAILS = [
  ["Trade size", "Uses the account’s current risk setting and buying power. If one contract does not fit, the bot skips it."],
  ["Position cap", "No more than two open positions at once, and never two positions in the same ticker."],
  ["Fast protection", "A hard option stop and an early losing-trade time limit stop a bad idea from becoming an all-day hope."],
  ["Winning trade plan", "At the first target, the system can lock in part of the gain and manage the remainder with the configured trail and time rule."],
  ["Daily safety lock", "After the configured daily loss limit, new entries pause while existing positions continue to be managed."],
];

function CoachChart({ focus }: { focus: number }) {
  // Real TSLA 5-minute bars from a completed V2 opening-range pullback session.
  // This is a deliberately short replay of the setup window, not a fictional all-day staircase.
  const bars = [["9:30",308.04,311.40,307.09,311.30,33102],["9:35",311.38,312.39,310.515,312.18,14632],["9:40",312.54,313.25,310.79,313.25,11560],["9:45",313.37,317.14,313.37,316.13,36903],["9:50",315.92,316.54,314.475,315.215,24038],["9:55",315.14,315.14,313.44,313.54,17072],["10:00",313.945,315.24,313.715,314.735,16596],["10:05",314.57,315.955,314.415,315.45,6980],["10:10",314.74,315.465,314.4,315.005,7080],["10:15",314.83,315.39,314.06,315.39,8221],["10:20",315.51,315.775,314.64,314.82,8562],["10:25",314.675,314.9,314.33,314.77,4144],["10:30",314.99,317.21,314.99,316.78,9467],["10:35",316.82,317.66,316.69,317.56,10723],["10:40",317,317.66,316.7,317.66,5605],["10:45",317.48,318.28,317.13,317.76,13101]] as const;
  const left = 50, right = 710, top = 76, bottom = 290, minPrice = 306.5, maxPrice = 319;
  const y = (price: number) => bottom - ((price - minPrice) / (maxPrice - minPrice)) * (bottom - top);
  const x = (index: number) => left + index * ((right - left) / (bars.length - 1));
  let cumulativePV = 0; let cumulativeVolume = 0;
  const vwap = bars.map(([, , high, low, close, volume]) => { cumulativePV += ((high + low + close) / 3) * volume; cumulativeVolume += volume; return cumulativePV / cumulativeVolume; });
  const focusIndex = [1, 3, 5, 15, 15][focus];
  const focusX = x(focusIndex), focusY = y(bars[focusIndex][4]);
  const rangeHigh = 313.25, rangeLow = 307.09;
  const stage = focus === 0 ? "Build the range" : focus === 1 ? "Break beyond the range" : focus === 2 ? "First retest" : focus === 3 ? "Finished confirmation" : "Protect below the retest";
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 5-minute candle replay</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 382" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Real TSLA 5-minute ORB lesson chart showing opening range, break, retest, confirmation and VWAP">
      {[76,130,183,237,290].map((gridY) => <line key={`h-${gridY}`} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7" strokeWidth="1" />)}
      {[0,3,6,9,12,15].map((index) => <line key={`v-${index}`} x1={x(index)} y1={top} x2={x(index)} y2={bottom} stroke="#f4f6f9" strokeWidth="1" />)}
      <rect x={x(0) - 16} y={y(rangeHigh)} width={x(2) - x(0) + 32} height={y(rangeLow) - y(rangeHigh)} rx="5" fill="#eaf2ff" stroke="#2870f4" strokeWidth="1.5" strokeDasharray="5 4" />
      <text x={x(0) - 12} y={y(rangeHigh) - 9} fill="#1768e8" fontSize="12" fontWeight="700">OPENING RANGE · 9:30–9:45</text>
      <line x1={x(0) - 16} y1={y(rangeHigh)} x2={x(2) + 16} y2={y(rangeHigh)} stroke="#2870f4" strokeWidth="1.4"/><text x={x(2) + 20} y={y(rangeHigh) + 4} fill="#1768e8" fontSize="10">range high</text>
      <line x1={x(0) - 16} y1={y(rangeLow)} x2={x(2) + 16} y2={y(rangeLow)} stroke="#2870f4" strokeWidth="1.4"/><text x={x(2) + 20} y={y(rangeLow) + 4} fill="#1768e8" fontSize="10">range low</text>
      <rect x={focusX - 19} y={Math.max(top, focusY - 47)} width="38" height="96" rx="6" fill="#2d73f5" fillOpacity=".05" stroke="#2d73f5" strokeWidth="1.3" strokeDasharray="4 4" />
      {bars.map(([time, open, high, low, close], index) => { const green = close >= open; const color = green ? "#17a35a" : "#e54b47"; const candleX = x(index); return <g key={time}><line x1={candleX} x2={candleX} y1={y(high)} y2={y(low)} stroke={color} strokeWidth="1.1"/><rect x={candleX - 4.5} y={Math.min(y(open), y(close))} width="9" height={Math.max(3.2, Math.abs(y(open) - y(close)))} rx="0.8" fill={color}/></g>; })}
      <path d={vwap.map((value, index) => `${index === 0 ? "M" : "L"}${x(index)} ${y(value)}`).join(" ")} fill="none" stroke="#ef921e" strokeWidth="1.6" />
      <text x="654" y={y(vwap[15]) - 8} fill="#ed8515" fontSize="12" fontWeight="700">VWAP</text>
      <line x1={x(3)} y1={y(317.14) - 40} x2={x(3)} y2={y(316.13)} stroke="#25354d" strokeWidth="1.2" /><circle cx={x(3)} cy={y(316.13)} r="4" fill="#25354d"/><rect x={x(3)-26} y={y(317.14)-61} width="52" height="19" rx="4" fill="#182132"/><text x={x(3)-19} y={y(317.14)-48} fill="white" fontSize="10" fontWeight="700">BREAK</text>
      <line x1={x(5)} y1={y(313.44) + 32} x2={x(5)} y2={y(313.44)} stroke="#2870f4" strokeWidth="1.2"/><circle cx={x(5)} cy={y(313.44)} r="4" fill="#2870f4"/><rect x={x(5)-29} y={y(313.44)+35} width="58" height="18" rx="4" fill="#2870f4"/><text x={x(5)-22} y={y(313.44)+48} fill="white" fontSize="10" fontWeight="700">RETEST</text>
      <line x1={x(15)} y1={y(318.28) - 37} x2={x(15)} y2={y(317.76)} stroke="#25354d" strokeWidth="1.2"/><circle cx={x(15)} cy={y(317.76)} r="4" fill="#25354d"/><rect x={x(15)-28} y={y(318.28)-58} width="56" height="19" rx="4" fill="#182132"/><text x={x(15)-21} y={y(318.28)-45} fill="white" fontSize="10" fontWeight="700">PROOF</text>
      <circle cx={focusX} cy={focusY} r="7" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {[0,3,6,9,12,15].map((index) => <text key={bars[index][0]} x={x(index) - 13} y="315" fill="#6b778c" fontSize="11">{bars[index][0]}</text>)}
      <text x="50" y="353" fill="#68768a" fontSize="11">1. Draw the first 15-minute range</text><text x="273" y="353" fill="#68768a" fontSize="11">2. Wait for break + retest</text><text x="510" y="353" fill="#68768a" fontSize="11">3. Enter only on proof above VWAP</text>
    </svg>
  </div>;
}

function TrendContinuationChart({ focus }: { focus: number }) {
  // Real paid-data SPY five-minute sequence from 2026-05-13.  The completed
  // 12:10 candle broke the prior eight-bar high; the paid option entry used
  // the next available 12:15 ask and the same contract's 30-minute bid.
  const bars = [
    ["11:30",739.260,739.620,738.980,739.620,739.126,738.610],
    ["11:35",739.560,739.810,739.550,739.810,739.297,738.712],
    ["11:40",739.810,740.220,739.810,740.110,739.439,738.838],
    ["11:45",740.040,740.095,739.870,739.910,739.572,738.996],
    ["11:50",739.880,739.995,739.560,739.960,739.632,739.053],
    ["11:55",739.840,739.840,739.570,739.750,739.632,739.273],
    ["12:00",739.700,740.180,739.650,740.135,739.766,739.343],
    ["12:05",740.155,740.340,739.990,740.330,739.861,739.482],
    ["12:10",740.335,740.660,740.270,740.610,740.008,739.485],
    ["12:15",740.755,740.755,740.500,740.665,740.173,739.661],
    ["12:20",740.690,741.830,740.660,741.620,740.462,739.869],
    ["12:25",741.670,741.910,741.400,741.760,740.738,740.098],
  ] as const;
  const left = 52, right = 710, top = 66, bottom = 286, minPrice = 738.65, maxPrice = 742.05;
  const x = (index: number) => left + index * ((right - left) / (bars.length - 1));
  const y = (price: number) => bottom - ((price - minPrice) / (maxPrice - minPrice)) * (bottom - top);
  const focusIndex = [2, 5, 8, 9, 11][focus];
  const priorHigh = 740.34;
  const stage = ["EMA 10 leads EMA 20", "Controlled pause", "12:10 close breaks the 8-bar high", "Next-minute option ask", "Same-contract 30-minute bid"][focus];
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>SPY · real 5-minute Trend Continuation replay</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 365" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Real SPY five-minute Trend Continuation chart with EMA 10, EMA 20, prior eight-bar high, signal close and next-minute entry">
      {[66,121,176,231,286].map((gridY) => <line key={`h-${gridY}`} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7" />)}
      {bars.map(([time], index) => <line key={time} x1={x(index)} y1={top} x2={x(index)} y2={bottom} stroke="#f4f6f9" />)}
      <rect x={x(0)-15} y={y(priorHigh)} width={x(7)-x(0)+30} height={y(739.55)-y(priorHigh)} rx="5" fill="#eef4ff" stroke="#397cf3" strokeDasharray="5 4" />
      <text x={x(0)-10} y={y(priorHigh)-9} fill="#1768e8" fontSize="11" fontWeight="700">PRIOR 8-BAR RANGE · high 740.34</text>
      {bars.map(([time, open, high, low, close], index) => { const color = close >= open ? "#17a35a" : "#e54b47"; return <g key={`c-${time}`}><line x1={x(index)} x2={x(index)} y1={y(high)} y2={y(low)} stroke={color}/><rect x={x(index)-6} y={Math.min(y(open), y(close))} width="12" height={Math.max(3.2, Math.abs(y(open)-y(close)))} rx="1" fill={color}/></g>; })}
      <path d={bars.map((bar,index) => `${index ? "L" : "M"}${x(index)} ${y(bar[5])}`).join(" ")} fill="none" stroke="#8055d9" strokeWidth="1.6"/><path d={bars.map((bar,index) => `${index ? "L" : "M"}${x(index)} ${y(bar[6])}`).join(" ")} fill="none" stroke="#ef921e" strokeWidth="1.6"/>
      <text x={right-55} y={y(bars[bars.length-1][5])-7} fill="#7250cc" fontSize="11" fontWeight="700">EMA 10</text><text x={right-55} y={y(bars[bars.length-1][6])+15} fill="#ed8515" fontSize="11" fontWeight="700">EMA 20</text>
      <rect x={x(focusIndex)-19} y={top+5} width="38" height={bottom-top-10} rx="6" fill="#2d73f5" fillOpacity=".045" stroke="#2d73f5" strokeDasharray="4 4"/>
      <line x1={x(8)} y1={y(740.66)-38} x2={x(8)} y2={y(740.61)} stroke="#25354d"/><circle cx={x(8)} cy={y(740.61)} r="4" fill="#25354d"/><rect x={x(8)-31} y={y(740.66)-58} width="62" height="18" rx="4" fill="#182132"/><text x={x(8)-24} y={y(740.66)-45} fill="white" fontSize="9" fontWeight="700">SIGNAL</text>
      <line x1={x(9)} y1={y(740.50)+41} x2={x(9)} y2={y(740.665)} stroke="#2870f4"/><circle cx={x(9)} cy={y(740.665)} r="4" fill="#2870f4"/><text x={x(9)-30} y={y(740.50)+56} fill="#1768e8" fontSize="10" fontWeight="700">ENTRY QUOTE</text>
      <circle cx={x(focusIndex)} cy={y(bars[focusIndex][4])} r="7" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {bars.map(([time], index) => index % 2 === 0 && <text key={`t-${time}`} x={x(index)-17} y="312" fill="#6b778c" fontSize="10">{time}</text>)}
      <text x="52" y="345" fill="#68768a" fontSize="11">1. Trend alignment</text><text x="272" y="345" fill="#68768a" fontSize="11">2. Completed 8-bar breakout</text><text x="516" y="345" fill="#68768a" fontSize="11">3. Next-minute ask</text>
    </svg>
  </div>;
}

function TwoLegTrendChart({ focus }: { focus: number }) {
  // Real TSLA one-minute sequence from 2025-08-06.  The reviewed state
  // machine identified its valid impulse at 10:17, pullback at 10:18 and
  // completed reclaim at 10:19; the paid option entry followed at 10:20.
  const bars = [
    ["10:00",313.945,314.100,313.940,314.100,314.577,314.120,313.176],["10:01",313.715,314.650,313.715,314.445,314.662,314.187,313.238],["10:02",313.955,315.240,313.930,314.770,314.538,314.360,313.263],["10:03",314.375,314.880,314.300,314.880,314.495,314.529,313.275],["10:04",314.970,314.970,314.490,314.735,314.602,314.605,313.306],["10:05",314.570,315.230,314.415,314.955,314.611,314.732,313.325],["10:06",315.120,315.500,315.120,315.385,314.817,315.014,313.341],["10:07",315.450,315.945,315.370,315.885,314.869,315.164,313.364],["10:08",315.955,315.955,315.765,315.780,315.126,315.175,313.383],["10:09",315.945,315.945,315.305,315.450,315.237,315.065,313.397],["10:10",314.740,314.830,314.530,314.830,315.200,314.968,313.407],["10:11",314.825,314.980,314.825,314.845,315.143,315.078,313.412],["10:12",314.560,314.610,314.400,314.610,315.017,315.145,313.417],["10:13",314.725,315.155,314.725,315.135,315.070,314.998,313.443],["10:14",315.080,315.465,315.005,315.005,315.115,314.886,313.462],["10:15",314.830,315.190,314.830,315.020,315.163,314.958,313.477],["10:16",314.770,314.810,314.060,314.550,315.026,314.857,313.490],["10:17",314.455,314.620,314.305,314.530,314.883,314.878,313.498],["10:18",314.420,314.960,314.390,314.960,314.815,314.723,313.507],["10:19",315.330,315.390,315.055,315.390,314.932,314.862,313.524],["10:20",315.510,315.775,315.365,315.365,314.987,314.957,313.545],
  ] as const;
  const left = 52, right = 710, top = 64, bottom = 286, minPrice = 312.95, maxPrice = 316.15;
  const x = (index: number) => left + index * ((right-left)/(bars.length-1)); const y = (price: number) => bottom-((price-minPrice)/(maxPrice-minPrice))*(bottom-top);
  const focusIndex = [13,17,18,19,20][focus]; const stage = ["VWAP + EMA alignment", "One-ATR impulse", "Controlled pullback toward EMA 9", "Completed reclaim", "Next-minute ask → 90-minute bid"][focus];
  const events = [
    { index: 17, label: "IMPULSE", price: 314.62, number: 1 },
    { index: 18, label: "PULLBACK", price: 314.39, number: 2 },
    { index: 19, label: "RECLAIM", price: 315.39, number: 3 },
    { index: 20, label: "ENTRY", price: 315.365, number: 4 },
  ];
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · real 1-minute Two-Leg replay</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 365" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Real TSLA one-minute Two-Leg Trend Pullback chart showing aligned trend, impulse, pullback, reclaim and next-minute option entry">
      {[64,120,175,231,286].map((gridY)=><line key={gridY} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7"/>)}
      <line x1={left} y1={y(313.67)} x2={right} y2={y(313.67)} stroke="#5a94ed" strokeDasharray="5 4"/><text x={left+5} y={y(313.67)-7} fill="#1768e8" fontSize="10" fontWeight="700">9:45 REFERENCE · 313.67</text>
      {bars.map(([time,open,high,low,close],index)=>{const color=close>=open?"#17a35a":"#e54b47";return <g key={time}><line x1={x(index)} x2={x(index)} y1={y(high)} y2={y(low)} stroke={color}/><rect x={x(index)-3.5} y={Math.min(y(open),y(close))} width="7" height={Math.max(3,Math.abs(y(open)-y(close)))} rx=".7" fill={color}/></g>})}
      <path d={bars.map((bar,index)=>`${index?"L":"M"}${x(index)} ${y(bar[5])}`).join(" ")} fill="none" stroke="#8055d9" strokeWidth="1.5"/><path d={bars.map((bar,index)=>`${index?"L":"M"}${x(index)} ${y(bar[6])}`).join(" ")} fill="none" stroke="#3c7af9" strokeWidth="1.4"/><path d={bars.map((bar,index)=>`${index?"L":"M"}${x(index)} ${y(bar[7])}`).join(" ")} fill="none" stroke="#ef921e" strokeWidth="1.5"/>
      <text x={right-50} y={y(bars[bars.length-1][5])-9} fill="#7250cc" fontSize="10" fontWeight="700">EMA 9</text><text x={right-50} y={y(bars[bars.length-1][6])+12} fill="#2d73f5" fontSize="10" fontWeight="700">EMA 20</text><text x={right-40} y={y(bars[bars.length-1][7])+15} fill="#ed8515" fontSize="10" fontWeight="700">VWAP</text>
      <rect x={x(focusIndex)-13} y={top+5} width="26" height={bottom-top-10} rx="5" fill="#2d73f5" fillOpacity=".045" stroke="#2d73f5" strokeDasharray="4 4"/>
      {events.map((event, eventIndex) => <g key={event.label}>
        <line x1={x(event.index)} y1={y(event.price) - 19} x2={x(event.index)} y2={y(event.price)} stroke={event.label === "ENTRY" ? "#2870f4" : "#25354d"} strokeWidth="1.1" />
        <circle cx={x(event.index)} cy={y(event.price)} r="8" fill={event.label === "ENTRY" ? "#2870f4" : "#25354d"} stroke="white" strokeWidth="2" />
        <text x={x(event.index)} y={y(event.price) + 3.2} textAnchor="middle" fill="white" fontSize="8" fontWeight="800">{event.number}</text>
        <rect x={350 + eventIndex * 91} y="18" width="82" height="24" rx="12" fill={event.label === "ENTRY" ? "#eaf1ff" : "#f4f6f9"} stroke={event.label === "ENTRY" ? "#2870f4" : "#dfe5ee"} />
        <text x={391 + eventIndex * 91} y="34" textAnchor="middle" fill={event.label === "ENTRY" ? "#1768e8" : "#36455d"} fontSize="9" fontWeight="800">{event.number}. {event.label}</text>
      </g>)}
      <circle cx={x(focusIndex)} cy={y(bars[focusIndex][4])} r="6.5" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {bars.map(([time],index)=>index%4===0&&<text key={`t-${time}`} x={x(index)-14} y="312" fill="#6b778c" fontSize="10">{time}</text>)}
      <text x="52" y="345" fill="#68768a" fontSize="11">1. Impulse leg</text><text x="275" y="345" fill="#68768a" fontSize="11">2. Pullback leg</text><text x="510" y="345" fill="#68768a" fontSize="11">3. Completed reclaim</text>
    </svg>
  </div>;
}

function AfternoonFvgChart({ focus }: { focus: number }) {
  // SPY five-minute candles from 2026-05-12. This is a real qualifying
  // paid-data FVG signal at 14:35 ET, not an invented all-day staircase.
  const bars = [
    ["13:50",734.655,735.085,734.48,735.05], ["13:55",735.13,735.20,734.765,735.08],
    ["14:00",735.02,735.25,734.805,735.20], ["14:05",735.19,735.19,734.75,734.95],
    ["14:10",734.94,735.115,734.70,735.085], ["14:15",735.09,735.33,735.04,735.23],
    ["14:20",735.245,735.82,735.24,735.74], ["14:25",735.96,736.48,735.91,736.19],
    ["14:30",736.18,736.44,736.08,736.08], ["14:35",736.01,736.40,735.88,736.09],
  ] as const;
  const left = 52, right = 710, top = 66, bottom = 286, minPrice = 734.10, maxPrice = 736.75;
  const x = (index: number) => left + index * ((right - left) / (bars.length - 1));
  const y = (price: number) => bottom - ((price - minPrice) / (maxPrice - minPrice)) * (bottom - top);
  const focusIndex = [0, 7, 9, 9, 9][focus];
  const stage = ["Afternoon window is open", "The upward gap is formed", "First return to the gap", "VWAP + EMA trend agree", "Next-minute entry → 30-minute bid exit"][focus];
  const gapLower = 735.82, gapUpper = 736.08;
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>SPY · 5-minute afternoon FVG replay</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 365" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Real SPY afternoon Fair Value Gap lesson chart showing the three-candle gap, first retest, VWAP and EMA alignment">
      {[66,121,176,231,286].map((gridY) => <line key={`h-${gridY}`} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7" strokeWidth="1" />)}
      {bars.map(([time], index) => <line key={time} x1={x(index)} y1={top} x2={x(index)} y2={bottom} stroke="#f4f6f9" strokeWidth="1" />)}
      <rect x={x(6) - 13} y={y(gapUpper)} width={x(9) - x(6) + 26} height={y(gapLower) - y(gapUpper)} rx="5" fill="#dfeaff" fillOpacity=".92" stroke="#2870f4" strokeWidth="1.35" strokeDasharray="5 4" />
      <text x={x(6) + 5} y={y(gapUpper) - 9} fill="#1f6fff" fontSize="12" fontWeight="700">FVG · 735.82–736.08</text>
      <text x={x(6) + 5} y={y(gapLower) + 15} fill="#55739c" fontSize="10">price moved through this zone quickly</text>
      {bars.map(([time, open, high, low, close], index) => { const green = close >= open; const color = green ? "#17a35a" : "#e54b47"; const candleX = x(index); return <g key={time}><line x1={candleX} x2={candleX} y1={y(high)} y2={y(low)} stroke={color} strokeWidth="1.15"/><rect x={candleX - 7} y={Math.min(y(open), y(close))} width="14" height={Math.max(3.4, Math.abs(y(open) - y(close)))} rx="1" fill={color}/></g>; })}
      <line x1={left} y1={y(734.30)} x2={right} y2={y(734.30)} stroke="#ef921e" strokeWidth="1.4" strokeDasharray="5 4" /><text x={right - 38} y={y(734.30) - 7} fill="#ed8515" fontSize="12" fontWeight="700">VWAP</text>
      <path d={`M${x(3)} ${y(734.92)} L${x(9)} ${y(735.72)}`} fill="none" stroke="#8055d9" strokeWidth="1.6" /><text x={right - 65} y={y(735.72) - 6} fill="#7250cc" fontSize="11" fontWeight="700">EMA 8 ↑</text>
      <rect x={x(focusIndex) - 20} y={top + 7} width="40" height={bottom - top - 14} rx="6" fill="#2d73f5" fillOpacity=".045" stroke="#2d73f5" strokeWidth="1.2" strokeDasharray="4 4" />
      <line x1={x(7)} y1={y(736.48) - 36} x2={x(7)} y2={y(736.19)} stroke="#25354d" strokeWidth="1.2"/><circle cx={x(7)} cy={y(736.19)} r="4" fill="#25354d"/><rect x={x(7)-22} y={y(736.48)-57} width="45" height="19" rx="4" fill="#182132"/><text x={x(7)-15} y={y(736.48)-44} fill="white" fontSize="10" fontWeight="700">GAP</text>
      <line x1={x(9)} y1={y(736.40) - 36} x2={x(9)} y2={y(736.09)} stroke="#2870f4" strokeWidth="1.2"/><circle cx={x(9)} cy={y(736.09)} r="4" fill="#2870f4"/><rect x={x(9)-31} y={y(736.40)-57} width="62" height="19" rx="4" fill="#2870f4"/><text x={x(9)-24} y={y(736.40)-44} fill="white" fontSize="10" fontWeight="700">RETEST</text>
      <circle cx={x(focusIndex)} cy={y(bars[focusIndex][4])} r="7" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {bars.map(([time], index) => <text key={`label-${time}`} x={x(index)-14} y="311" fill="#6b778c" fontSize="10">{time}</text>)}
      <text x="52" y="345" fill="#68768a" fontSize="11">1. Window: 1:30–3:00</text><text x="278" y="345" fill="#68768a" fontSize="11">2. First retest only</text><text x="511" y="345" fill="#68768a" fontSize="11">3. VWAP + EMA agree</text>
    </svg>
  </div>;
}

function FailedRangeRecoveryChart({ focus }: { focus: number }) {
  const bars = [
    ["9:40", 100.05, 100.28, 99.92, 100.20], ["9:44", 100.20, 100.32, 100.02, 100.12],
    ["10:06", 100.18, 100.52, 100.15, 100.47], ["10:07", 100.48, 100.56, 100.16, 100.22],
    ["10:08", 100.21, 100.25, 99.98, 100.04], ["10:09", 100.03, 100.08, 99.82, 99.90],
  ] as const;
  const left = 70, right = 700, top = 62, bottom = 286, minPrice = 99.55, maxPrice = 100.72;
  const x = (index: number) => left + index * ((right - left) / (bars.length - 1));
  const y = (price: number) => bottom - ((price - minPrice) / (maxPrice - minPrice)) * (bottom - top);
  const focusIndex = [1, 2, 3, 4, 5][focus];
  const stage = ["Opening range fixed", "Completed break outside", "Failure closes back inside", "Room remains to VWAP", "Contract + order intent next"][focus];
  const orHigh = 100.32, orLow = 99.92, vwap = 99.72;
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>SPY · 1-minute failed-range recovery</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 355" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="SPY failed opening-range breakout lesson showing the opening range, completed break, recovery inside, VWAP room, and next-minute execution">
      {[62,118,174,230,286].map((gridY) => <line key={gridY} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7" />)}
      <rect x={left - 18} y={y(orHigh)} width={x(1) - left + 38} height={y(orLow) - y(orHigh)} rx="5" fill="#e8f0ff" stroke="#2870f4" strokeWidth="1.35" strokeDasharray="5 4" />
      <text x={left - 9} y={y(orHigh) - 9} fill="#1f6fff" fontSize="11" fontWeight="800">OPENING RANGE · 9:30–9:44</text>
      <line x1={left - 18} y1={y(orHigh)} x2={right} y2={y(orHigh)} stroke="#2870f4" strokeWidth="1.15" strokeDasharray="5 4" />
      <line x1={left - 18} y1={y(orLow)} x2={right} y2={y(orLow)} stroke="#2870f4" strokeWidth="1.15" strokeDasharray="5 4" />
      <text x={right - 63} y={y(orHigh) - 6} fill="#1f6fff" fontSize="10">OR HIGH</text><text x={right - 56} y={y(orLow) + 15} fill="#1f6fff" fontSize="10">OR LOW</text>
      <line x1={left} y1={y(vwap)} x2={right} y2={y(vwap)} stroke="#ef921e" strokeWidth="1.5" /><text x={right - 42} y={y(vwap) - 7} fill="#ed8515" fontSize="11" fontWeight="700">VWAP</text>
      {bars.map(([time, open, high, low, close], index) => { const green = close >= open; const color = green ? "#17a35a" : "#e54b47"; return <g key={time}><line x1={x(index)} x2={x(index)} y1={y(high)} y2={y(low)} stroke={color} strokeWidth="1.2"/><rect x={x(index)-9} y={Math.min(y(open), y(close))} width="18" height={Math.max(4, Math.abs(y(open)-y(close)))} rx="1" fill={color}/></g>; })}
      <rect x={x(focusIndex)-25} y={top+5} width="50" height={bottom-top-10} rx="6" fill="#2870f4" fillOpacity=".045" stroke="#2870f4" strokeDasharray="4 4" />
      <line x1={x(2)} y1={y(100.52)-35} x2={x(2)} y2={y(100.47)} stroke="#25354d"/><rect x={x(2)-26} y={y(100.52)-55} width="52" height="18" rx="4" fill="#182132"/><text x={x(2)} y={y(100.52)-42} textAnchor="middle" fill="white" fontSize="9" fontWeight="800">BREAK</text>
      <line x1={x(3)} y1={y(100.56)-35} x2={x(3)} y2={y(100.22)} stroke="#c73535"/><rect x={x(3)-29} y={y(100.56)-55} width="58" height="18" rx="4" fill="#c73535"/><text x={x(3)} y={y(100.56)-42} textAnchor="middle" fill="white" fontSize="9" fontWeight="800">FAILED</text>
      <circle cx={x(focusIndex)} cy={y(bars[focusIndex][4])} r="7" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {bars.map(([time], index) => <text key={`t-${time}`} x={x(index)-15} y="310" fill="#6b778c" fontSize="10">{time}</text>)}
      <text x="70" y="340" fill="#68768a" fontSize="11">1. Range</text><text x="250" y="340" fill="#68768a" fontSize="11">2. Break outside</text><text x="445" y="340" fill="#68768a" fontSize="11">3. Close back inside → reverse</text>
    </svg>
  </div>;
}


export function StrategyPlaybookExperience({ activeLessonIds, strategyCatalog }: { activeLessonIds: LessonId[]; strategyCatalog: ReviewedStrategyCatalogEntry[] }) {
  const [selectedId, setSelectedId] = useState<LessonId>(activeLessonIds[0] ?? "v2_orb");
  const [stepIndex, setStepIndex] = useState(0);
  const [answer, setAnswer] = useState<number | null>(null);
  const [showGuardrails, setShowGuardrails] = useState(false);
  const [narrationPlaying, setNarrationPlaying] = useState(false);
  const [narrationProgress, setNarrationProgress] = useState(0);
  const [narrationError, setNarrationError] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const activeCourses = COURSES.filter((course) => activeLessonIds.includes(course.id));
  const course = activeCourses.find((item) => item.id === selectedId) ?? activeCourses[0];
  const step = course?.steps[stepIndex];
  const catalogEntry = course ? strategyCatalog.find((item) => item.strategy_id === STRATEGY_ID_BY_LESSON[course.id]) : undefined;
  const evidence = catalogEntry ? EVIDENCE_LABELS[catalogEntry.evidence_grade] : undefined;

  useEffect(() => {
    if (activeCourses.length && !activeCourses.some((item) => item.id === selectedId)) {
      setSelectedId(activeCourses[0].id);
      setStepIndex(0);
    }
  }, [activeCourses, selectedId]);

  if (!course || !step) return null;
  const audioSrc = `/audio/coach-celo/${course.id}/${step.label.toLowerCase()}.mp3`;

  const chooseCourse = (id: LessonId) => {
    audioRef.current?.pause(); setNarrationPlaying(false); setNarrationProgress(0); setNarrationError(false);
    setSelectedId(id); setStepIndex(0); setAnswer(null);
  };
  const chooseStep = (next: number) => { audioRef.current?.pause(); setNarrationPlaying(false); setNarrationProgress(0); setNarrationError(false); setStepIndex(Math.max(0, Math.min(next, course.steps.length - 1))); setAnswer(null); };
  const toggleNarration = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => setNarrationError(true));
    else audio.pause();
  };

  return <section className="flex flex-col gap-4 max-w-[1500px]">
    <div><h2 className="text-[28px] leading-tight font-bold tracking-tight" style={{ color: "#102950" }}>Strategy Playbook</h2><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Learn your currently available strategies one visual lesson at a time.</p></div>
    <div className="flex gap-3 flex-wrap" role="tablist" aria-label="Active strategy lessons">
      {activeCourses.map((item) => <button key={item.id} onClick={() => chooseCourse(item.id)} role="tab" aria-selected={item.id === course.id} className="rounded-lg px-5 py-3 text-sm font-semibold transition-colors" style={{ border: item.id === course.id ? "1.5px solid #2970f6" : "1px solid var(--border)", color: item.id === course.id ? "#1e66ed" : "var(--ink-muted)", background: item.id === course.id ? "#f6f9ff" : "var(--surface)", boxShadow: item.id === course.id ? "0 4px 14px rgba(41,112,246,.08)" : "none" }}>{item.shortTitle}</button>)}
    </div>
    <div className="grid gap-4 items-stretch" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(300px, .34fr)" }}>
      <div className="card overflow-hidden p-0" style={{ boxShadow: "0 10px 32px rgba(23,47,82,.07)" }}>
        <div className="px-5 pt-4 pb-3 grid gap-4 items-center" style={{ gridTemplateColumns: "minmax(300px, .62fr) minmax(400px, 1fr)", borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3"><div className="w-10 h-10 rounded-full grid place-items-center font-bold text-base text-white" style={{ background: course.id === "v2_orb" || course.id === "v2_two_leg" ? "#e8262d" : "#296df5" }}>{course.id === "v2_spy_fvg" ? "⚡" : course.id === "v2_recovery" ? "↩" : course.id === "v2_orb" || course.id === "v2_two_leg" ? "T" : "↗"}</div><div><div className="flex items-center gap-2 flex-wrap"><span className="font-bold text-sm" style={{ color: "var(--ink)" }}>{course.id === "v2_orb" || course.id === "v2_two_leg" ? "TSLA" : "SPY"}</span><span className="text-sm" style={{ color: "var(--ink-muted)" }}>{course.shortTitle}</span><span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ background: "#edf4ff", color: "#2368e9" }}>{course.id === "v2_two_leg" || course.id === "v2_recovery" ? "1m" : "5m"}</span>{catalogEntry && evidence && <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" title={evidence.detail} style={{ color: evidence.color, background: evidence.background }}>{evidence.label}</span>}</div><p className="text-[11px] mt-1" style={{ color: "var(--ink-muted)" }}>Lesson {stepIndex + 1} of {course.steps.length}{catalogEntry ? ` · ${catalogEntry.exit_minutes}m timed exit` : ""}</p>{catalogEntry?.integrity_errors.length ? <p className="text-[11px] mt-1 font-semibold" style={{ color: "#c73535" }}>Integrity check blocked this strategy.</p> : null}</div></div>
          <div className="flex items-start justify-between gap-1" aria-label="Lesson steps">{course.steps.map((item, index) => <button key={item.label} onClick={() => chooseStep(index)} className="flex-1 min-w-0 flex flex-col items-center gap-1.5 group"><span className="w-7 h-7 rounded-full grid place-items-center text-xs font-bold transition-colors" style={{ background: index === stepIndex ? "#1f6fff" : "#f1f3f7", color: index === stepIndex ? "white" : "#546176", boxShadow: index === stepIndex ? "0 0 0 4px #eaf1ff" : "none" }}>{index + 1}</span><span className="text-[11px] font-medium whitespace-nowrap" style={{ color: index === stepIndex ? "#1f6fff" : "#536075" }}>{item.label}</span></button>)}</div>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="min-w-0">{course.id === "v2_spy_fvg" ? <AfternoonFvgChart focus={step.chartFocus} /> : course.id === "v2_recovery" ? <FailedRangeRecoveryChart focus={step.chartFocus} /> : course.id === "v2_trend" ? <TrendContinuationChart focus={step.chartFocus} /> : course.id === "v2_two_leg" ? <TwoLegTrendChart focus={step.chartFocus} /> : <CoachChart focus={step.chartFocus} />}</div>
          <div className="flex items-center justify-between gap-3"><button className="btn btn-ghost btn-sm" disabled={stepIndex === 0} onClick={() => chooseStep(stepIndex - 1)}><ChevronLeft size={15} /> Back</button><div className="flex-1 max-w-[440px] h-1 rounded-full" style={{ background: "#e5ecf8" }}><div className="h-full rounded-full" style={{ width: `${((stepIndex + 1) / course.steps.length) * 100}%`, background: "#2870f4" }} /></div><button className="btn btn-primary btn-sm" onClick={() => chooseStep(stepIndex === course.steps.length - 1 ? 0 : stepIndex + 1)}>{stepIndex === course.steps.length - 1 ? "Replay" : "Next"} <ChevronRight size={15} /></button></div>
        </div>
        {showGuardrails ? <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface))", border: "1px solid var(--border)" }}><div className="flex gap-3 items-start"><img src={COACH_IMAGE} alt="Coach Celo" className="w-12 h-16 object-contain object-bottom shrink-0" /><div><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Coach Celo explains the account guardrails</p><p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>These rules apply in paper and live modes. They control risk across the account.</p></div></div><div className="grid gap-2 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>{GUARDRAILS.map(([title, detail]) => <div key={title} className="rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{title}</p><p className="text-xs leading-relaxed mt-1" style={{ color: "var(--ink-muted)" }}>{detail}</p></div>)}</div></div> : <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "#fbfcff", border: "1px solid #e7edf7" }}><p className="text-base font-bold" style={{ color: "var(--ink)" }}>Try it yourself</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{step.question}</p><div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>{step.answers.map((choice, index) => <button key={choice} className="btn text-left justify-start" onClick={() => setAnswer(index)} style={answer === index ? { borderColor: index === step.correct ? "var(--positive)" : "var(--negative)", background: index === step.correct ? "var(--positive-bg)" : "var(--negative-bg)" } : undefined}><span className="w-6 h-6 rounded-full grid place-items-center text-xs mr-1" style={{ background: "#edf4ff", color: "#1f6fff" }}>{index + 1}</span>{choice}</button>)}</div>{answer !== null && <p className="text-xs mt-3 leading-relaxed" style={{ color: answer === step.correct ? "var(--positive)" : "var(--ink-muted)" }}>{answer === step.correct ? step.answerWhy : `Not quite. ${step.answerWhy}`}</p>}</div>}
      </div>
        <aside className="rounded-2xl overflow-hidden flex flex-col" style={{ background: "linear-gradient(160deg, #08234a 0%, #0a2e63 100%)", color: "white", boxShadow: "0 18px 36px rgba(11, 35, 75, .15)" }}>
          <audio ref={audioRef} src={audioSrc} preload="metadata" onPlay={() => setNarrationPlaying(true)} onPause={() => setNarrationPlaying(false)} onEnded={() => { setNarrationPlaying(false); setNarrationProgress(0); }} onError={() => setNarrationError(true)} onTimeUpdate={(event) => { const audio = event.currentTarget; setNarrationProgress(audio.duration ? (audio.currentTime / audio.duration) * 100 : 0); }} />
          <div className="px-5 pt-5 h-[250px] relative overflow-hidden">
            <p className="relative z-10 text-center text-base font-bold">Coach Celo</p><div className="mx-auto mt-1 w-8 h-0.5 rounded-full" style={{ background: "#337dff" }} />
            <div className="absolute inset-x-0 top-[42px] h-[300px] flex justify-center overflow-hidden" style={{ background: "radial-gradient(circle at 50% 30%, rgba(55,124,255,.22), transparent 54%)" }}><img src={COACH_IMAGE} alt="Coach Celo, your strategy instructor" className="w-[245px] max-w-[82%] h-auto self-start" /></div>
          </div>
          <div className="px-4 pb-4 flex flex-col gap-4">
            <div className="relative -mt-2 rounded-2xl p-4 text-sm leading-relaxed" style={{ background: "#fff", color: "#273955", boxShadow: "0 8px 18px rgba(0,0,0,.17)" }}><span className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 rotate-45 bg-white" /><div className="relative"><strong>Coach Celo says:</strong> {step.lesson}<p className="mt-2 text-xs leading-relaxed" style={{ color: "#64718a" }}>{step.coach}</p></div></div>
            <button className="w-full rounded-xl px-3 py-2.5 flex items-center gap-3 text-left" onClick={toggleNarration} style={{ background: "rgba(100,151,255,.15)", border: "1px solid rgba(173,204,255,.34)", color: "white" }} aria-label={narrationPlaying ? "Pause Coach Celo narration" : "Play Coach Celo narration"}>
              <span className="w-8 h-8 shrink-0 rounded-full grid place-items-center" style={{ background: "#3c7af9" }}>{narrationPlaying ? <span className="text-xs font-black">Ⅱ</span> : <Play size={14} fill="white" />}</span>
              <div className="min-w-0 flex-1"><p className="text-xs font-semibold">{narrationError ? "Narration unavailable" : "Hear Coach Celo"}</p><div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,.22)" }}><div className="h-full rounded-full" style={{ width: `${narrationProgress || 0}%`, minWidth: narrationProgress ? undefined : "8px", background: "#80b1ff" }} /></div></div><span className="text-[10px]" style={{ color: "#bcd2ff" }}>{narrationPlaying ? "Playing" : "Audio"}</span>
            </button>
            <div><p className="text-[11px] uppercase tracking-[.15em] font-semibold mb-2" style={{ color: "#a9c7ff" }}>What to watch</p><ul className="flex flex-col gap-2.5">{step.watch.map((item) => <li key={item} className="flex gap-2 text-xs leading-relaxed" style={{ color: "#eff5ff" }}><Check size={14} className="shrink-0 mt-0.5" style={{ color: "#69df9c" }} />{item}</li>)}</ul></div>
            <div className="rounded-xl p-3 text-xs leading-relaxed" style={{ background: "rgba(255,105,143,.16)", color: "#ffdce8", borderLeft: "3px solid #ff7295" }}><strong style={{ color: "white" }}>Avoid the chop:</strong> {step.avoid}</div>
            <button className="btn btn-sm self-start" onClick={() => setShowGuardrails((value) => !value)} style={{ background: showGuardrails ? "#4a83ff" : "transparent", color: "white", borderColor: "#5576aa" }}><ShieldCheck size={14} />{showGuardrails ? "Back to lesson" : "See the safety rules"}</button>
          </div>
        </aside>
    </div>
  </section>;
}
