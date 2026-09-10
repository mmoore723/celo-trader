"""Whole-contract partial-sale accounting, separate from one-contract runner."""
from strategy_health.authored_exit_summary import net_profit


def partial_summary(rows):
    profits=[]
    partials=quotes=0
    for row in rows:
        path=row.get('premium_path') or {}
        quotes+=path.get('quote_count',0)
        runner=net_profit(row)
        if runner is None:
            continue
        first=runner
        if path.get('partial_bid') is not None:
            first=net_profit({**row,'bid':path['partial_bid']})
            if first is None:
                continue
            partials+=1
        profits.append(first+runner)
    gains=sum(p for p in profits if p>0)
    losses=-sum(p for p in profits if p<0)
    return {'results':len(profits),'partial_sales':partials,'quotes_observed':quotes,
            'net_two_contract_pnl':round(sum(profits),2) if profits else None,
            'profit_factor':round(gains/losses,2) if losses else ('infinite' if gains else None)}
