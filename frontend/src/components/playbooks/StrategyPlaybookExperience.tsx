import { useEffect, useRef, useState } from "react";
import {
  Check, ChevronLeft, ChevronRight, Play, ShieldCheck,
} from "lucide-react";

type LessonId = "v2_orb" | "v2_trend" | "v2_momentum";
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
    title: "TSLA Trend Continuation",
    shortTitle: "Trend Continuation",
    level: "Intermediate · 5 steps",
    description: "A trend needs structure, a pause, and proof that momentum has resumed before an entry is considered.",
    steps: [
      { label: "Trend", title: "Start with a real trend", lesson: "The quick trend line must be above the slower line for a call idea, or below it for a put idea. Price needs to be holding that same side.", coach: "A flat or crossed chart is not a trend. It is a wait.", watch: ["Both trend lines pointing together", "Price holding the same side", "Finished 5-minute candles"], avoid: "Crossing, flat lines are chop. We do not predict which way they will break.", chartFocus: 0, question: "What makes a trend usable?", answers: ["Lines pointing the same way", "The biggest candle", "The cheapest option"], correct: 0, answerWhy: "Right. The direction has to agree before a continuation setup can make sense." },
      { label: "Pause", title: "Let the trend breathe", lesson: "A healthy trend often pauses or pulls back. We want a controlled pause, not a collapse through the structure.", coach: "The pause gives the next move room to prove itself. We do not buy the middle of a burst.", watch: ["A shallow pullback", "Structure still holding", "Price not losing its trend side"], avoid: "A sharp reversal is not a pause. Do not call it one because you want a trade.", chartFocus: 1, question: "What do we wait for after a strong trend move?", answers: ["A controlled pause", "More random candles", "A larger position"], correct: 0, answerWhy: "Right. The pause is where the bot looks for a safer continuation opportunity." },
      { label: "Resume", title: "Wait for momentum to resume", lesson: "The completed signal candle must close through its recent mini-range in the direction of the trend.", coach: "We want the next push to show up on a finished candle—not halfway through one.", watch: ["Close beyond the mini-range", "Trend direction still intact", "Reasonable option spread"], avoid: "Do not enter while a candle is still forming. It can look strong and finish weak.", chartFocus: 2, question: "Why wait for the candle to finish?", answers: ["It gives the rule a completed fact", "It guarantees a winner", "It makes the option cheaper"], correct: 0, answerWhy: "Right. A completed candle gives the bot a real, repeatable signal instead of a moving target." },
      { label: "Confirm", title: "Enter with the trend, not against it", lesson: "When structure, direction, and the completed signal agree, the paper model records the next available option quote.", coach: "This is a simple rule: the chart gives the direction first, then the option is chosen.", watch: ["Structure and signal agree", "The next available quote", "A spread the account can handle"], avoid: "The bot never looks at a future candle to make an entry look smarter.", chartFocus: 3, question: "Which comes first: the option or the chart signal?", answers: ["The chart signal", "The option premium", "A prediction"], correct: 0, answerWhy: "Right. The chart creates the idea. The option is selected afterward to express it." },
      { label: "Protect", title: "Risk rules protect the trend trade too", lesson: "An invalidation level sits beyond the signal structure. If that structure breaks, the trend idea did not hold and the bot follows its exit rules.", coach: "A trade needs an exit before it needs hope. The same account safety rules protect every strategy.", watch: ["The structural invalidation", "VWAP and momentum changes", "The account-wide guardrails"], avoid: "Do not add contracts because a trend trade is losing.", chartFocus: 4, question: "What should happen when trend structure fails?", answers: ["Exit by the rule", "Double the position", "Move the stop farther away"], correct: 0, answerWhy: "Right. We limit the loss when the original trend story stops being true." },
    ],
  },
  {
    id: "v2_momentum",
    title: "TSLA Adaptive Momentum",
    shortTitle: "Adaptive Momentum",
    level: "Intermediate · 5 steps",
    description: "A one-minute rule that acts only when TSLA moves farther than its own recent normal movement for that time of day.",
    steps: [
      { label: "Baseline", title: "Learn what normal looks like", lesson: "Before judging today, the bot looks at the same time of day across the previous 14 TSLA sessions. That creates a changing normal-movement zone, not one fixed number.", coach: "Morning and afternoon do not move the same way. The zone adjusts to the clock so normal noise does not look like momentum.", watch: ["Exactly 14 completed earlier sessions", "The same clock time on each session", "A zone that changes through the day"], avoid: "If fewer than 14 prior sessions are available, the bot does not guess or fill in missing history. It waits.", chartFocus: 0, question: "Why does the zone change during the day?", answers: ["TSLA's normal movement changes by time of day", "To make more trades", "Because the option price chooses it"], correct: 0, answerWhy: "Right. The comparison is fair only when 10:30 is compared with earlier 10:30 behavior, and so on." },
      { label: "Zone", title: "See the adaptive noise zone", lesson: "The blue band is the normal movement area built from those 14 earlier sessions. Movement inside it is ordinary enough that the bot does nothing.", coach: "A lot of candles look exciting. If they stay in the blue zone, they have not earned a trade.", watch: ["Price still inside the blue zone", "The upper and lower adaptive boundaries", "A completed one-minute candle"], avoid: "Do not trade every green or red candle. Inside the zone is the bot's no-trade area.", chartFocus: 1, question: "Price remains inside the adaptive zone. What should the bot do?", answers: ["Wait", "Buy a call", "Buy a put"], correct: 0, answerWhy: "Right. Inside the zone is normal movement, not enough evidence for momentum." },
      { label: "Signal", title: "An unusual move earns attention", lesson: "At the half-hour checks, a completed one-minute candle that moves outside the adaptive zone creates a direction signal. Above the upper boundary is bullish; below the lower boundary is bearish.", coach: "The boundary is the evidence. We are not predicting the next candle before it finishes.", watch: ["A finished one-minute candle", "Close outside the correct boundary", "Direction matches the boundary crossed"], avoid: "A temporary spike can disappear before the minute ends. The strategy uses completed bars, not a moving price.", chartFocus: 2, question: "What turns movement into a momentum signal?", answers: ["A close outside the adaptive zone", "Any big-looking candle", "A low option premium"], correct: 0, answerWhy: "Right. The completed close must be outside the learned zone." },
      { label: "Entry", title: "Enter on the next minute's quote", lesson: "After the signal completes, the option model uses the next minute's actual ask price for entry. It does not pretend that it bought at the previous candle's close.", coach: "This keeps the backtest honest. The signal comes first; the next available option quote is the entry.", watch: ["Signal minute is complete", "Next available option ask", "7–21 days to expiration and a tight spread"], avoid: "A chart signal is not a free fill. The option's bid-ask spread still has to be acceptable.", chartFocus: 3, question: "When does this strategy enter after a valid signal?", answers: ["At the next minute's option ask", "At a perfect past price", "Before the signal minute finishes"], correct: 0, answerWhy: "Right. Entering at the next available quote avoids using information that was not available yet." },
      { label: "Close", title: "Close the same contract at 3:59", lesson: "This tested version holds the same selected contract until 3:59 PM ET, then records its actual bid as the exit. It does not carry options into the close.", coach: "The exit is a simple clock rule for this version, so we can judge the entry rule cleanly without changing the finish line trade by trade.", watch: ["The exact same contract", "The 3:59 PM bid", "Account-wide safety limits"], avoid: "Never assume a future closing price. The study and paper journal use the available bid at 3:59 PM.", chartFocus: 4, question: "What does this tested version use for its exit?", answers: ["Same contract's 3:59 PM bid", "Tomorrow's opening price", "The highest price of the day"], correct: 0, answerWhy: "Right. The exit is a predeclared, repeatable 3:59 PM rule." },
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

function MomentumChart({ focus }: { focus: number }) {
  // Educational one-minute replay: the blue band is the 14-prior-session
  // time-of-day adaptive zone. It is intentionally labeled as a teaching
  // illustration rather than a live trade chart.
  const bars = [["10:00",100.00,100.15,99.94,100.08],["10:01",100.07,100.16,99.99,100.03],["10:02",100.03,100.18,100.00,100.14],["10:03",100.14,100.24,100.08,100.19],["10:04",100.19,100.27,100.12,100.17],["10:05",100.17,100.21,100.07,100.09],["10:06",100.09,100.18,100.03,100.15],["10:07",100.15,100.33,100.12,100.29],["10:08",100.29,100.44,100.25,100.41],["10:09",100.41,100.58,100.36,100.53],["10:10",100.53,100.67,100.48,100.62],["10:11",100.62,100.77,100.57,100.72],["10:12",100.72,100.84,100.64,100.78],["10:13",100.78,100.91,100.70,100.88]] as const;
  const left = 54, right = 710, top = 65, bottom = 268, minPrice = 99.75, maxPrice = 101.05;
  const x = (index: number) => left + index * ((right - left) / (bars.length - 1));
  const y = (price: number) => bottom - ((price - minPrice) / (maxPrice - minPrice)) * (bottom - top);
  const upper = [100.32,100.33,100.34,100.35,100.36,100.37,100.38,100.40,100.42,100.44,100.46,100.48,100.50,100.52];
  const lower = [99.76,99.75,99.74,99.73,99.72,99.71,99.70,99.69,99.68,99.67,99.66,99.65,99.64,99.63];
  const focusIndex = [2,5,9,10,13][focus];
  const stage = ["Build the 14-session baseline", "Inside the normal zone: wait", "Signal: close beyond the upper zone", "Next-minute option entry", "Same contract closes at 3:59 PM"][focus];
  const zonePath = `${upper.map((value, index) => `${index === 0 ? "M" : "L"}${x(index)} ${y(value)}`).join(" ")} ${lower.slice().reverse().map((value, reverseIndex) => `L${x(lower.length - 1 - reverseIndex)} ${y(value)}`).join(" ")} Z`;
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 1-minute adaptive momentum replay</span><span className="text-[11px] shrink-0" style={{ color: "#2368e9" }}>{stage}</span></div>
    <svg viewBox="0 0 760 360" className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="TSLA adaptive momentum lesson chart showing the 14-session adaptive normal-movement zone, signal, next-minute entry, and 3:59 PM exit">
      {[65,116,167,218,268].map((gridY) => <line key={`h-${gridY}`} x1={left} y1={gridY} x2={right} y2={gridY} stroke="#edf1f7" strokeWidth="1" />)}
      {[0,3,6,9,12].map((index) => <line key={`v-${index}`} x1={x(index)} y1={top} x2={x(index)} y2={bottom} stroke="#f4f6f9" strokeWidth="1" />)}
      <path d={zonePath} fill="#dceaff" fillOpacity=".78" stroke="#5a95ff" strokeWidth="1.2" strokeDasharray="5 4" />
      <text x="63" y="88" fill="#2269e8" fontSize="12" fontWeight="700">NORMAL MOVEMENT ZONE</text><text x="63" y="103" fill="#5d7190" fontSize="10">Built from the previous 14 TSLA sessions at this time of day</text>
      {bars.map(([time, open, high, low, close], index) => { const green = close >= open; const color = green ? "#17a35a" : "#e54b47"; const candleX = x(index); return <g key={time}><line x1={candleX} x2={candleX} y1={y(high)} y2={y(low)} stroke={color} strokeWidth="1.2"/><rect x={candleX - 8} y={Math.min(y(open), y(close))} width="16" height={Math.max(3.5, Math.abs(y(open) - y(close)))} rx="1" fill={color}/></g>; })}
      <rect x={x(focusIndex) - 17} y={top + 10} width="34" height={bottom - top - 20} rx="6" fill="#2870f4" fillOpacity=".045" stroke="#2870f4" strokeWidth="1.25" strokeDasharray="4 4" />
      <line x1={x(9)} y1={y(100.58) - 36} x2={x(9)} y2={y(100.53)} stroke="#25354d" strokeWidth="1.2"/><circle cx={x(9)} cy={y(100.53)} r="4" fill="#25354d"/><rect x={x(9)-27} y={y(100.58)-57} width="54" height="19" rx="4" fill="#182132"/><text x={x(9)-20} y={y(100.58)-44} fill="white" fontSize="10" fontWeight="700">SIGNAL</text>
      <line x1={x(10)} y1={y(100.67) - 36} x2={x(10)} y2={y(100.62)} stroke="#2870f4" strokeWidth="1.2"/><circle cx={x(10)} cy={y(100.62)} r="4" fill="#2870f4"/><rect x={x(10)-25} y={y(100.67)-57} width="50" height="19" rx="4" fill="#2870f4"/><text x={x(10)-18} y={y(100.67)-44} fill="white" fontSize="10" fontWeight="700">ENTRY</text>
      <path d={`M${x(10)} ${y(100.62)} L${x(13)} ${y(100.88)}`} fill="none" stroke="#18a35a" strokeWidth="1.5" strokeDasharray="4 3"/><text x={x(12)-12} y={y(100.88)-18} fill="#13854a" fontSize="11" fontWeight="700">3:59 exit</text>
      <circle cx={x(focusIndex)} cy={y(bars[focusIndex][4])} r="7" fill="#2870f4" stroke="white" strokeWidth="3" />
      {[0,3,6,9,12].map((index) => <text key={bars[index][0]} x={x(index)-13} y="295" fill="#6b778c" fontSize="11">{bars[index][0]}</text>)}
      <text x="54" y="334" fill="#68768a" fontSize="11">1. Learn normal</text><text x="239" y="334" fill="#68768a" fontSize="11">2. Ignore inside-zone noise</text><text x="475" y="334" fill="#68768a" fontSize="11">3. Signal → next-minute entry → 3:59 exit</text>
    </svg>
  </div>;
}

export function StrategyPlaybookExperience({ activeLessonIds }: { activeLessonIds: LessonId[] }) {
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
    <div><h2 className="text-[28px] leading-tight font-bold tracking-tight" style={{ color: "#102950" }}>Strategy Playbook</h2><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Learn our current paper strategies one visual lesson at a time.</p></div>
    <div className="flex gap-3 flex-wrap" role="tablist" aria-label="Active strategy lessons">
      {activeCourses.map((item) => <button key={item.id} onClick={() => chooseCourse(item.id)} role="tab" aria-selected={item.id === course.id} className="rounded-lg px-5 py-3 text-sm font-semibold transition-colors" style={{ border: item.id === course.id ? "1.5px solid #2970f6" : "1px solid var(--border)", color: item.id === course.id ? "#1e66ed" : "var(--ink-muted)", background: item.id === course.id ? "#f6f9ff" : "var(--surface)", boxShadow: item.id === course.id ? "0 4px 14px rgba(41,112,246,.08)" : "none" }}>{item.shortTitle}</button>)}
    </div>
    <div className="grid gap-4 items-stretch" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(300px, .34fr)" }}>
      <div className="card overflow-hidden p-0" style={{ boxShadow: "0 10px 32px rgba(23,47,82,.07)" }}>
        <div className="px-5 pt-4 pb-3 grid gap-4 items-center" style={{ gridTemplateColumns: "minmax(250px, .55fr) minmax(400px, 1fr)", borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3"><div className="w-10 h-10 rounded-full grid place-items-center font-bold text-base text-white" style={{ background: course.id === "v2_orb" ? "#e8262d" : "#296df5" }}>{course.id === "v2_orb" ? "T" : "↗"}</div><div><div className="flex items-center gap-2"><span className="font-bold text-sm" style={{ color: "var(--ink)" }}>TSLA</span><span className="text-sm" style={{ color: "var(--ink-muted)" }}>{course.shortTitle}</span><span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ background: "#edf4ff", color: "#2368e9" }}>5m</span></div><p className="text-[11px] mt-1" style={{ color: "var(--ink-muted)" }}>Lesson: {stepIndex + 1} of {course.steps.length}</p></div></div>
          <div className="flex items-start justify-between gap-1" aria-label="Lesson steps">{course.steps.map((item, index) => <button key={item.label} onClick={() => chooseStep(index)} className="flex-1 min-w-0 flex flex-col items-center gap-1.5 group"><span className="w-7 h-7 rounded-full grid place-items-center text-xs font-bold transition-colors" style={{ background: index === stepIndex ? "#1f6fff" : "#f1f3f7", color: index === stepIndex ? "white" : "#546176", boxShadow: index === stepIndex ? "0 0 0 4px #eaf1ff" : "none" }}>{index + 1}</span><span className="text-[11px] font-medium whitespace-nowrap" style={{ color: index === stepIndex ? "#1f6fff" : "#536075" }}>{item.label}</span></button>)}</div>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="min-w-0">{course.id === "v2_momentum" ? <MomentumChart focus={step.chartFocus} /> : <CoachChart focus={step.chartFocus} />}</div>
          <div className="flex items-center justify-between gap-3"><button className="btn btn-ghost btn-sm" disabled={stepIndex === 0} onClick={() => chooseStep(stepIndex - 1)}><ChevronLeft size={15} /> Back</button><div className="flex-1 max-w-[440px] h-1 rounded-full" style={{ background: "#e5ecf8" }}><div className="h-full rounded-full" style={{ width: `${((stepIndex + 1) / course.steps.length) * 100}%`, background: "#2870f4" }} /></div><button className="btn btn-primary btn-sm" onClick={() => chooseStep(stepIndex === course.steps.length - 1 ? 0 : stepIndex + 1)}>{stepIndex === course.steps.length - 1 ? "Replay" : "Next"} <ChevronRight size={15} /></button></div>
        </div>
        {showGuardrails ? <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface))", border: "1px solid var(--border)" }}><div className="flex gap-3 items-start"><img src={COACH_IMAGE} alt="Coach Celo" className="w-12 h-16 object-contain object-bottom shrink-0" /><div><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Coach Celo explains the account guardrails</p><p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>These rules are shared by every paper strategy. They control risk across the account.</p></div></div><div className="grid gap-2 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>{GUARDRAILS.map(([title, detail]) => <div key={title} className="rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{title}</p><p className="text-xs leading-relaxed mt-1" style={{ color: "var(--ink-muted)" }}>{detail}</p></div>)}</div></div> : <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "#fbfcff", border: "1px solid #e7edf7" }}><p className="text-base font-bold" style={{ color: "var(--ink)" }}>Try it yourself</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{step.question}</p><div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>{step.answers.map((choice, index) => <button key={choice} className="btn text-left justify-start" onClick={() => setAnswer(index)} style={answer === index ? { borderColor: index === step.correct ? "var(--positive)" : "var(--negative)", background: index === step.correct ? "var(--positive-bg)" : "var(--negative-bg)" } : undefined}><span className="w-6 h-6 rounded-full grid place-items-center text-xs mr-1" style={{ background: "#edf4ff", color: "#1f6fff" }}>{index + 1}</span>{choice}</button>)}</div>{answer !== null && <p className="text-xs mt-3 leading-relaxed" style={{ color: answer === step.correct ? "var(--positive)" : "var(--ink-muted)" }}>{answer === step.correct ? step.answerWhy : `Not quite. ${step.answerWhy}`}</p>}</div>}
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
