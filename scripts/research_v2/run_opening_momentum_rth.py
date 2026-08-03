"""Run exploratory opening-momentum research; never eligible for promotion."""
from __future__ import annotations
import argparse,json,sys
from dataclasses import asdict
from datetime import datetime,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research_v2.data import load_csv
from research_v2.simulator import SimulationConfig,Simulator
from research_v2.strategies import OpeningMomentumRTH
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward
def pack(x):return {"passed":x.passed,"trade_count":x.trade_count,"net_pnl":x.net_pnl,"expectancy":x.expectancy,"profit_factor":x.profit_factor,"max_drawdown_pct":x.max_drawdown_pct,"reasons":list(x.reasons)}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--csv',required=True);p.add_argument('--split',required=True);a=p.parse_args();d=load_csv(a.csv);s=Simulator(SimulationConfig(session_exit_time=time(15,55)));r=run_walk_forward(d.bars,datetime.fromisoformat(a.split.replace('Z','+00:00')),OpeningMomentumRTH,s,ValidationConfig());cfg=asdict(s.config);cfg['session_exit_time']=s.config.session_exit_time.isoformat();print(json.dumps({"research_only":True,"exploratory_only":True,"strategy":OpeningMomentumRTH.strategy_id,"dataset_sha256":d.sha256,"simulation":cfg,"train":pack(r.train_validation),"holdout":pack(r.holdout_validation),"promoted":False},indent=2,sort_keys=True))
if __name__=='__main__':main()
