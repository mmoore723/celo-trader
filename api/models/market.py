"""
api/models/market.py — Bar / quote / scanner-result schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class Bar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float]
    vwap_upper1: Optional[float]
    vwap_lower1: Optional[float]
    vwap_upper2: Optional[float]
    vwap_lower2: Optional[float]
    rvol: Optional[float]
    atr: Optional[float]


class Quote(BaseModel):
    ticker: str
    price: float
    change_pct: float
    volume: float


class ScannerResult(BaseModel):
    ticker: str
    rvol: float
    price: float
    atr: float
    change_pct: float
    rank: int
