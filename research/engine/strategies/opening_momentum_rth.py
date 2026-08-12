"""Exploratory first-30-minute momentum candidate, kept out of promotion."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import time
from typing import Sequence
from research.engine.models import Bar, Side, Signal
from research.engine.strategies.gap_fill_rth import _atr

@dataclass(frozen=True)
class OpeningMomentumRTHConfig:
    opening_bars: int = 6
    min_move_pct: float = .0015
    atr_bars: int = 14
    atr_trail_multiple: float = 2.0
    def __post_init__(self):
        if self.opening_bars < 3 or not 0 < self.min_move_pct < .05 or self.atr_bars < 2 or self.atr_trail_multiple <= 0:
            raise ValueError("invalid opening momentum configuration")

class OpeningMomentumRTH:
    strategy_id = "V2_OPENING_MOMENTUM_RTH_EXPLORATORY"
    def __init__(self, config: OpeningMomentumRTHConfig = OpeningMomentumRTHConfig()):
        self.config=config; self._seen=0; self._last_timestamp=None; self._history=[]; self._today=[]; self._emitted_day=None
    def _session(self,bars:Sequence[Bar]):
        current=bars[-1]
        if len(bars)==self._seen+1 and (self._seen==0 or bars[-2].timestamp==self._last_timestamp):
            self._today=self._today+[current] if self._today and self._today[-1].timestamp.date()==current.timestamp.date() else [current]
            self._history.append(current)
        else:
            self._history=list(bars); self._today=[bar for bar in bars if bar.timestamp.date()==current.timestamp.date()]
        self._seen,self._last_timestamp=len(bars),current.timestamp
        return self._today
    def evaluate(self,bars:Sequence[Bar]):
        today=self._session(bars); current=today[-1]
        if self._emitted_day==current.timestamp.date() or len(today)!=self.config.opening_bars:
            return None
        atr=_atr(self._history,self.config.atr_bars)
        if atr is None or atr<=0: return None
        move=(current.close-today[0].open)/today[0].open
        if abs(move)<self.config.min_move_pct: return None
        side=Side.LONG if move>0 else Side.SHORT
        stop=current.close-atr*self.config.atr_trail_multiple if side is Side.LONG else current.close+atr*self.config.atr_trail_multiple
        target=current.close*(10 if side is Side.LONG else .1)
        self._emitted_day=current.timestamp.date()
        return Signal(self.strategy_id,side,current.timestamp,current.close,stop,target,{"opening_move_pct":round(move*100,4),"atr":round(atr,6),"atr_trail_multiple":self.config.atr_trail_multiple,"no_profit_target":True,"exploratory_only":True})
    def trailing_stop(self,signal,current_stop,bar,best_price):
        atr=_atr(self._history+[bar],self.config.atr_bars)
        if atr is None:return None
        return best_price-atr*self.config.atr_trail_multiple if signal.side is Side.LONG else best_price+atr*self.config.atr_trail_multiple
