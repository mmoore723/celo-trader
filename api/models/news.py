"""
api/models/news.py — News article schema.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class NewsArticle(BaseModel):
    id: Optional[int] = None
    headline: str
    summary: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    symbols: list[str] = []
