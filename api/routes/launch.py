"""Prelaunch interest collection. No billing, broker or trading integration."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from api.middleware.auth import require_auth
from auth.security import origin_is_trusted

router = APIRouter(prefix='/api/launch', tags=['launch'])
DB_PATH = Path(__file__).resolve().parents[2] / 'user_data' / 'launch_waitlist.db'
CONSENT = 'Email me CELO Trader launch updates. No purchase or trading account is created.'


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    DB_PATH.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS waitlist (email TEXT PRIMARY KEY, interest TEXT NOT NULL, created_at TEXT NOT NULL, consent TEXT NOT NULL, removal_hash TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS attempts (client_hash TEXT NOT NULL, at REAL NOT NULL)')
    conn.execute('CREATE INDEX IF NOT EXISTS attempts_time ON attempts(at)')
    conn.commit()
    return conn


class Interest(BaseModel):
    email: str = Field(max_length=254)
    interest: str = Field(default='watch', max_length=20)
    consent: bool
    website: str = Field(default='', max_length=200)


class Removal(BaseModel):
    token: str = Field(min_length=32, max_length=128)


def trusted_source(request):
    origin = request.headers.get('origin')
    if origin and not origin_is_trusted(origin):
        raise HTTPException(403, 'Please use the form on CeloTrader.com.')


@router.post('/waitlist')
def join_waitlist(body: Interest, request: Request):
    trusted_source(request)
    if body.website:
        return {'ok': True, 'message': 'Your request was received.'}
    email = body.email.strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", email) or '..' in email:
        raise HTTPException(422, 'Enter a valid email address.')
    if not body.consent:
        raise HTTPException(422, 'Please agree to receive launch updates.')
    if body.interest not in {'watch', 'learning', 'learning_discord', 'trading', 'undecided'}:
        raise HTTPException(422, 'Choose one of the four plans, or Not sure yet.')
    # Use the ASGI client, never trust a caller-supplied forwarding header.
    client = request.client.host if request.client else 'unknown'
    client_hash = hashlib.sha256(client.encode()).hexdigest()
    now = time.time()
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM attempts WHERE at < ?', (now - 3600,))
        if conn.execute('SELECT COUNT(*) FROM attempts WHERE client_hash=?', (client_hash,)).fetchone()[0] >= 10:
            raise HTTPException(429, 'Too many requests. Please try again in an hour.')
        conn.execute('INSERT INTO attempts VALUES (?, ?)', (client_hash, now))
        token = secrets.token_urlsafe(32)
        result = conn.execute('INSERT OR IGNORE INTO waitlist VALUES (?, ?, ?, ?, ?)',
            (email, body.interest, datetime.now(timezone.utc).isoformat(), CONSENT, hashlib.sha256(token.encode()).hexdigest()))
        created = result.rowcount == 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    response = {'ok': True, 'message': 'Your launch interest is saved. No payment or trading account was created.'}
    if created:
        response['removal_token'] = token
    return response


@router.post('/waitlist/remove')
def remove_interest(body: Removal, request: Request):
    trusted_source(request)
    conn = connect()
    try:
        conn.execute('DELETE FROM waitlist WHERE removal_hash=?', (hashlib.sha256(body.token.encode()).hexdigest(),))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'message': 'This signup has been removed, if it was still on the list.'}


@router.get('/waitlist', dependencies=[Depends(require_auth)])
def list_interest(request: Request, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100)):
    if not getattr(request.state, 'is_admin', False):
        raise HTTPException(403, 'Admin access required.')
    conn = connect()
    try:
        total = conn.execute('SELECT COUNT(*) FROM waitlist').fetchone()[0]
        rows = conn.execute('SELECT email, interest, created_at FROM waitlist ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, (page-1)*limit)).fetchall()
        return {'total': total, 'page': page, 'items': [dict(row) for row in rows], 'email_delivery': 'Not configured. Signups are saved only.'}
    finally:
        conn.close()
