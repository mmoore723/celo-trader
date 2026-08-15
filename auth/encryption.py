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
        from auth.security import is_production
        if is_production():
            raise RuntimeError("ENCRYPTION_KEY is required in production")
        # Auto-generate on first local run and persist before using it.
        key = Fernet.generate_key()
        _env_path = Path(__file__).resolve().parents[1] / ".env"
        try:
            from config.atomic_files import atomic_write_text
            existing = _env_path.read_text(encoding="utf-8") if _env_path.exists() else ""
            if any(line.startswith("ENCRYPTION_KEY=") for line in existing.splitlines()):
                raise RuntimeError("ENCRYPTION_KEY exists in .env but was not loaded")
            suffix = "" if not existing or existing.endswith("\n") else "\n"
            atomic_write_text(
                _env_path,
                f"{existing}{suffix}ENCRYPTION_KEY={key.decode()}\n",
                mode=0o600,
            )
            os.environ["ENCRYPTION_KEY"] = key.decode()
            logger.info("Generated new ENCRYPTION_KEY and saved to .env")
        except Exception as e:
            raise RuntimeError("Could not persist local ENCRYPTION_KEY") from e

    try:
        _fernet = Fernet(key)
    except Exception as exc:
        raise RuntimeError("ENCRYPTION_KEY is not a valid Fernet key") from exc
    return _fernet


def encrypt_dict(data: dict) -> str:
    """JSON-encode `data`, encrypt with Fernet, return base64 ciphertext string."""
    plaintext = json.dumps(data).encode()
    return _get_fernet().encrypt(plaintext).decode()


def decrypt_dict(ciphertext: str) -> dict:
    """Decrypt a Fernet ciphertext string and return the original dict."""
    plaintext = _get_fernet().decrypt(ciphertext.encode())
    return json.loads(plaintext.decode())
