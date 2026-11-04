import { useState } from 'react';

export function VersionRuleWalkthrough({version, steps, exit, selectedPolicy}: {version:string;steps:string[];exit:string;selectedPolicy:boolean}) {
  const [stage, setStage] = useState(0);
  const lessons = [
    {name:'Enter', title:'Wait for the setup, not the excitement.',
      idea:'An entry is the moment you buy the option to start a trade. A setup is the group of chart conditions you require before buying.',
      why:'A candle summarizes prices during a set period, such as one minute. Its close is the last price when that period ends. If your rule requires a close above a line, a brief move above it during the minute is not enough.',
      example:'Imagine price reaches your entry area, but one required signal is missing. You wait. A near-match is not the same setup.',
      detail: steps.length ? steps : ['The entry checklist for this version is not available yet.']},
    {name:'Protect', title:'Decide what would make you leave.',
      idea:'A stop-loss rule tells you when to leave a losing trade. A time limit tells you when to leave because your planned holding time has ended.',
      why:'A price stop says “the move went against my plan.” A timer says “my allotted time is up.” A support line on a chart is not automatically a stop the bot will use.',
      example:'Support is a price area where a fall previously paused or reversed. Imagine that area is $100 and the stock now falls below it. That only triggers the bot if this version has a rule to exit there. A timer alone does not do that.',
      detail:['Check the exit checklist before entering. It tells you which price or time condition this lesson uses.', 'A stop is an instruction, not a guaranteed sale price. A fast move or a wide option spread can make the loss larger.']},
    {name:'Exit', title:'Know your reason to sell.',
      idea: selectedPolicy ? 'This example uses the exit you selected.' : 'This example teaches the strategy’s original exit.',
      why:'Decide the exit before entering. Otherwise a small pullback can scare you out, or hope can keep you in after your rule says to leave.',
      example:'For a 30-minute example entered at 10:00, the time limit is 10:30. It is not “30 minutes after I start losing.” This example does not change your strategy’s actual time limit.',
      detail:[exit, 'An open trade keeps the exit rules it started with. The lesson does not change your bot.']},
    {name:'Size', title:'Choose the budget before the contracts.',
      idea:'A standard stock-option contract represents 100 shares. A $2 option costs $200 per contract, before fees.',
      why:'For these bot strategies, the sizing calculation budgets the whole option cost. It does not assume a support-line stop guarantees a smaller loss.',
      example:'Practice budget: $10,000 account × 2% = $200. At $2 per option, that fits one contract. Two would cost $400. These are example numbers, not your saved settings.',
      detail:['Bot calculation: account value × risk percentage ÷ (planned option price × 100). Round down to whole contracts.', 'The spending cap and available buying power can reduce that number. If the budget cannot cover one contract, skip the trade.', 'Only a plan with a defined option-price stop can use entry premium minus stop premium to estimate planned loss. A stock support level alone cannot tell you the option’s sale price. Even a stop can slip.']},
  ];
  const lesson = lessons[stage];
  return <section className="rounded-xl border p-4 space-y-3" aria-label="Entry exit stops and sizing">
    <h3 className="font-semibold">Build your trade plan</h3>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2" aria-label="Trade plan topics">{lessons.map((item,index) => <button key={item.name} aria-pressed={stage === index} className={`btn text-sm ${stage === index ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setStage(index)}>{item.name}</button>)}</div>
    <h4 className="font-semibold">{lesson.title}</h4>
    <p className="text-sm">{lesson.idea}</p>
    <p className="text-sm leading-relaxed">{lesson.why}</p>
    <p className="text-sm leading-relaxed"><strong>For example:</strong> {lesson.example}</p>
    <h5 className="text-sm font-semibold">{stage === 0 || stage === 2 ? `Your checklist · version ${version}` : 'Put it into practice'}</h5>
    <ul className="list-disc pl-5 text-sm space-y-2">{lesson.detail.map(text => <li key={text}>{text}</li>)}</ul>
  </section>;
}
