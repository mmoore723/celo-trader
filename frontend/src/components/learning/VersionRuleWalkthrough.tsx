import { useState } from 'react';

export function VersionRuleWalkthrough({version, steps, exit, selectedPolicy}: {version:string;steps:string[];exit:string;selectedPolicy:boolean}) {
  const [stage, setStage] = useState(0);
  const lessons = [
    {name:'Enter', title:'Wait for the setup, not the excitement.',
      idea:'A fast move gets your attention. Your entry checklist tells you whether to act.',
      why:'A candle can push above a line and fall back before it finishes. When your rule requires a completed candle, that early push is not enough.',
      example:'Imagine price reaches your entry area, but one required signal is missing. You wait. A near-match is not the same setup.',
      detail: steps.length ? steps : ['The entry checklist for this version is not available yet.']},
    {name:'Protect', title:'Decide what would make you leave.',
      idea:'A price stop and a time limit do different jobs.',
      why:'A price stop says “the move went against my plan.” A timer says “my allotted time is up.” A support line on a chart is not automatically a stop the bot will use.',
      example:'Imagine support is $100 and the stock falls below it. That only triggers the bot if this version has a rule to exit there. A timer alone does not do that.',
      detail:['Check the exit checklist before entering. It tells you which price or time condition this lesson uses.', 'A stop is an instruction, not a guaranteed sale price. A fast move or a wide option spread can make the loss larger.']},
    {name:'Exit', title:'Know your reason to sell.',
      idea: selectedPolicy ? 'This example uses the exit you selected.' : 'This example teaches the strategy’s original exit.',
      why:'Decide the exit before entering. Otherwise a small pullback can scare you out, or hope can keep you in after your rule says to leave.',
      example:'For a 30-minute example entered at 10:00, the time limit is 10:30. It is not “30 minutes after I start losing.” This example does not change your strategy’s actual time limit.',
      detail:[exit, 'An open trade keeps the exit rules it started with. The lesson does not change your bot.']},
    {name:'Size', title:'Choose the budget before the contracts.',
      idea:'One option contract controls 100 shares. A $2 option costs $200 per contract, before fees.',
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
    <details key={`why-${stage}`}><summary className="cursor-pointer text-sm">Why it matters</summary><p className="text-sm mt-2 leading-relaxed">{lesson.why}</p></details>
    <details key={`example-${stage}`}><summary className="cursor-pointer text-sm">Walk through an example</summary><p className="text-sm mt-2 leading-relaxed">{lesson.example}</p></details>
    <details key={`rules-${stage}`}><summary className="cursor-pointer text-sm">{stage === 0 || stage === 2 ? `Exact checklist · version ${version}` : 'Explain more'}</summary><ul className="list-disc pl-5 text-sm mt-2 space-y-2">{lesson.detail.map(text => <li key={text}>{text}</li>)}</ul></details>
  </section>;
}
