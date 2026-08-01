"""
api/models/options.py — Options chain row schema.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class OptionsChainRow(BaseModel):
    strike: float
    call_bid: Optional[float] = None
    call_ask: Optional[float] = None
    call_mid: Optional[float] = None
    call_delta: Optional[float] = None
    call_iv: Optional[float] = None
    call_oi: Optional[int] = None
    put_bid: Optional[float] = None
    put_ask: Optional[float] = None
    put_mid: Optional[float] = None
    put_delta: Optional[float] = None
    put_iv: Optional[float] = None
    put_oi: Optional[int] = None
