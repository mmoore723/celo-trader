"""Short-lived support sessions bound to both users and the Admin login."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from jose import jwt, JWTError
from auth.security import JWT_ALGORITHM, jwt_secret
COOKIE = 'celo_run_as'
DURATION = 1800

def audit(actor, target, action, **details):
    from auth.users import get_db
    conn = get_db()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS account_audit (at TEXT,actor TEXT,target TEXT,changes TEXT)')
        conn.execute('INSERT INTO account_audit VALUES(?,?,?,?)', (datetime.now(timezone.utc).isoformat(), actor, target, json.dumps({'action': action, **details})))
        conn.commit()
    finally: conn.close()

def issue(actor, target, primary_token):
    if not actor.get('is_admin') or actor.get('disabled'):
        raise ValueError('Administrator access required')
    if target.get('disabled') or target.get('is_admin') or target['user_id'] == actor['user_id']:
        raise ValueError('Choose an active, non-administrator user')
    now = int(datetime.now(timezone.utc).timestamp())
    p = dict(sub=target['user_id'], actor=actor['user_id'], actor_version=actor['session_version'], target_version=target['session_version'], session=sha256(primary_token.encode()).hexdigest(), iat=now, exp=now+DURATION, purpose='run_as')
    return jwt.encode(p, jwt_secret(), algorithm=JWT_ALGORITHM)

def resolve(actor, primary_token, support_token):
    if not support_token: return actor, None
    from auth.users import get_user
    p = jwt.decode(support_token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    target = get_user(str(p.get('sub') or ''))
    if (p.get('purpose') != 'run_as' or not actor.get('is_admin') or actor.get('disabled')
        or p.get('actor') != actor['user_id'] or p.get('actor_version') != actor['session_version']
        or p.get('session') != sha256(primary_token.encode()).hexdigest()
        or not target or target.get('disabled') or target.get('is_admin')
        or p.get('target_version') != target['session_version']):
        raise JWTError('Run as user session is no longer valid')
    return target, dict(actor_id=actor['user_id'], actor_name=actor['username'], target_name=target['username'], expires_at=p['exp'])
