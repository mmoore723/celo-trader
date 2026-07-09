"""
auth/encryption.py — Fernet symmetric encryption for stored API keys.

API keys (Alpaca + Tradier) are sensitive secrets.  Storing them in plain
JSON in user_data/ would expose them if the server is ever compromised.
Fernet (AES-128-CBC + HMAC-SHA256) encrypts them at rest.

Key management:
  - ENCRYPTION_KEY env var (hex string) is used as the Fernet key.
  - If absent on first boot, one is auto-generated and appended to .env.
  - Key is 32 raw bytes, base64url-encoded to produce the 44-char Fernet key.
"""
from __future__ import annotations
import os
import json
import base64
import logging
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger("celo_trader.auth.encryption")

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    raw = os.getenv("ENCRYPTION_KEY", "")
    if raw:
        # Accept either raw hex (64 chars) or already-encoded Fernet key (44 chars)
        if len(raw) == 64:
            key = base64.urlsafe_b64encode(bytes.fromhex(raw))
        else:
            key = raw.encode()
    else:
        # Auto-generate on first run and persist to .env
        key = Fernet.generate_key()
        _env_path = Path(__file__).resolve().parents[1] / ".env"
        try:
            with open(_env_path, "a") as f:
                f.write(f"\nENCRYPTION_KEY={key.decode()}\n")
            os.environ["ENCRYPTION_KEY"] = key.decode()
            logger.info("Generated new ENCRYPTION_KEY and saved to .env")
        except Exception as e:
            logger.warning("Could not save ENCRYPTION_KEY to .env: %s", e)

    _fernet = Fernet(key)
    return _fernet


def encrypt_dict(data: dict) -> str:
    """JSON-encode `data`, encrypt with Fernet, return base64 ciphertext string."""
    plaintext = json.dumps(data).encode()
    return _get_fernet().encrypt(plaintext).decode()


def decrypt_dict(ciphertext: str) -> dict:
    """Decrypt a Fernet ciphertext string and return the original dict."""
    plaintext = _get_fernet().decrypt(ciphertext.encode())
    return json.loads(plaintext.decode())
