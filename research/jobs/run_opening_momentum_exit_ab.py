"""Exploratory, predeclared ATR-trail A/B for TSLA opening momentum."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.engine.data import load_csv
from research.engine.simulator import SimulationConfig, Simulator
from research.engine.strategies import OpeningMomentumRTH, OpeningMomentumRTHConfig
from research.engine.validation import ValidationConfig
from research.engine.walk_forward import run_walk_forward

def pack(x): return {"passed":x.passed,"trade_count":x.trade_count,"net_pnl":x.net_pnl,"expectancy":x.expectancy,"profit_factor":x.profit_factor,"max_drawdown_pct":x.max_drawdown_pct,"reasons":list(x.reasons)}
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--csv',required=True); p.add_argument('--split',required=True); a=p.parse_args(); d=load_csv(a.csv); s=Simulator(SimulationConfig(session_exit_time=time(15,55))); results=[]
    for trail in (1.0,1.5,2.0,2.5,3.0):
        factory=lambda trail=trail: OpeningMomentumRTH(OpeningMomentumRTHConfig(atr_trail_multiple=trail))
        r=run_walk_forward(d.bars,datetime.fromisoformat(a.split.replace('Z','+00:00')),factory,s,ValidationConfig())
        results.append({"atr_trail_multiple":trail,"train":pack(r.train_validation),"holdout":pack(r.holdout_validation)})
    print(json.dumps({"research_only":True,"exploratory_only":True,"promotion_allowed":False,"strategy":"V2_OPENING_MOMENTUM_RTH_EXPLORATORY","dataset_sha256":d.sha256,"method":"predeclared ATR trail A/B; select only by train, then obtain fresh data before any promotion","variants":results},indent=2,sort_keys=True))
if __name__=='__main__': main()
