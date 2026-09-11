import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";

const money = (value: number | null) => value == null ? "—" : `$${value.toFixed(2)}`;

/** Supplemental evidence: collapsed by default, theme tokens, no trading action. */
export function ExpirationStudy({ study: s }: { study: StrategyTickerResearchPair["expiration_study"] }) {
  if (!s) return null;
  const date = s.first_setup_at ? new Date(`${s.first_setup_at.slice(0, 10)}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric" }) : null;
  const matched = s.matched;
  const missing = (s.statuses.missing_quote ?? 0) + (s.statuses.unmeasurable ?? 0);
  return <details className="rounded-lg px-3 py-2" style={{ background: "var(--surface-sunken)", color: "var(--ink-muted)" }}>
    <summary className="cursor-pointer"><b style={{ color: "var(--ink)" }}>8–21-day option study</b> · {matched.results} matched results · {s.longer_only.option_results} extra priced setups</summary>
    <p className="mt-2">{date ? `Started ${date}` : "No dated setup yet"} · {s.selected_contracts}/{s.setups} setups found an option · {s.non_overlapping.option_results} non-overlapping results</p>
    {matched.results > 0 ? <>
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-left">
          <caption className="text-left font-medium pb-1" style={{ color: "var(--ink)" }}>Same setups · Same strategy exit · After costs</caption>
          <thead><tr><th scope="col">Option rule</th><th scope="col">PF</th><th scope="col">P&amp;L</th><th scope="col">Typical result</th></tr></thead>
          <tbody>{([["Original", matched.primary], ["8–21 days", matched.longer]] as const).map(([name, value]) => <tr key={name}>
            <th scope="row" className="font-normal py-1">{name}</th><td>{researchProfitFactorText(value.profit_factor, value.option_results)}</td><td>{money(value.net_one_contract_pnl)}</td><td>{money(value.median_one_contract_pnl)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p>{matched.improved} better · {matched.worsened} worse · {matched.unchanged} unchanged · Average change {money(matched.average_change)} per contract</p>
    </> : <p className="mt-2">No completed same-setup comparison yet.</p>}
    {s.longer_only.option_results > 0 && <p className="mt-2">Only the 8–21-day rule found an option: {s.longer_only.option_results} results · PF {researchProfitFactorText(s.longer_only.profit_factor, s.longer_only.option_results)} · P&amp;L {money(s.longer_only.net_one_contract_pnl)}. These are not matched improvements.</p>}
    <details className="mt-2"><summary className="cursor-pointer">Rules and missing data</summary>
      <p>Nearest expiry in 8–21 days, then nearest out-of-the-money strike. Ask $1.50–$10; spread at most 8%. Uses each strategy’s own exit.</p>
      <p>{s.statuses.collecting ?? 0} open · {s.statuses.pending_quote ?? 0} awaiting exit price · {missing} missing usable exit data · {s.statuses.no_contract ?? 0} no option · {s.primary_incomplete} original results incomplete</p>
      <p>Non-overlapping matched tests: {s.matched_non_overlapping.results} · Original PF {researchProfitFactorText(s.matched_non_overlapping.primary.profit_factor, s.matched_non_overlapping.results)} · 8–21-day PF {researchProfitFactorText(s.matched_non_overlapping.longer.profit_factor, s.matched_non_overlapping.results)}</p>
      <p>Matched average result: original {money(matched.primary.average_one_contract_pnl)} · 8–21-day {money(matched.longer.average_one_contract_pnl)}. Largest closed-result drop: original {money(matched.primary.maximum_drawdown_one_contract)} · 8–21-day {money(matched.longer.maximum_drawdown_one_contract)}.</p>
      <p>Separate research prices—not broker fills. Does not change the main PF, recommendations, or your trading settings.</p>
    </details>
  </details>;
}
