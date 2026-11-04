import { useState } from 'react';

/** A rule diagram, not a fabricated price path or a simulated trade. */
export function VersionRuleWalkthrough({version, steps, exit, selectedPolicy}: {version:string;steps:string[];exit:string;selectedPolicy:boolean}) {
  const [stage, setStage] = useState(0);
  const stages = [
    {name:'Setup and entry', text:steps.length ? steps.join(' ') : 'No verified entry lesson is published for this version. No substitute entry is being shown.'},
    {name:'Protect the play', text:'Identify the active invalidation rule in the exit reference. Do not assume a chart level or indicator is an active stop. If this version only has a timer, a price move alone does not imply it exits.'},
    {name:'Exit', text:exit},
    {name:'Size before entering', text:'Calculate the dollar budget, divide by risk per contract, round down, then apply the premium-spend and buying-power limits. The sizing lesson below explains what the bot actually budgets.'},
  ];
  return <section className="rounded-xl border p-4 space-y-3" aria-label="Version rule diagram">
    <h3 className="font-semibold">How version {version} works</h3>
    <p className="text-xs">{selectedPolicy ? 'Selected exit policy' : 'Research baseline reference'}. This diagram changes with the selected variation. It is not a price chart or a broker fill.</p>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2" role="tablist" aria-label="Version lesson stages">{stages.map((item,index) => <button key={item.name} id={`version-stage-${index}`} role="tab" aria-selected={stage === index} aria-controls="version-stage-content" className={`btn text-sm ${stage === index ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setStage(index)}>{index + 1}. {item.name}</button>)}</div>
    <p id="version-stage-content" role="tabpanel" aria-labelledby={`version-stage-${stage}`} className="text-sm leading-relaxed">{stages[stage].text}</p>
  </section>;
}
