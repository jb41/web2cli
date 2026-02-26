"""Encrypted session storage.

Sessions are stored at ~/.web2cli/sessions/<domain>.json.enc
using Fernet symmetric encryption derived from machine identity.
"""

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SESSIONS_DIR = Path.home() / ".web2cli" / "sessions"
FIXED_SALT = b"web2cli-session-store-v1"


def _get_encryption_key() -> bytes:
    """Derive a Fernet key from hostname + username + fixed string.

    This is NOT a high-security secret vault — it's obfuscation
    to prevent casual reading of cookie values on disk.
    """
    identity = f"{os.uname().nodename}:{os.getlogin()}:web2cli"
    dk = hashlib.pbkdf2_hmac("sha256", identity.encode(), FIXED_SALT, 100_000)
    return base64.urlsafe_b64encode(dk)


def _ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_session(domain: str, data: dict) -> None:
    """Encrypt and persist session data for a domain."""
    _ensure_dir()
    fernet = Fernet(_get_encryption_key())
    encrypted = fernet.encrypt(json.dumps(data).encode())
    path = SESSIONS_DIR / f"{domain}.json.enc"
    path.write_bytes(encrypted)
    path.chmod(0o600)


def load_session(domain: str) -> dict | None:
    """Load and decrypt session for a domain. Returns None if missing/corrupt."""
    path = SESSIONS_DIR / f"{domain}.json.enc"
    if not path.exists():
        return None
    try:
        fernet = Fernet(_get_encryption_key())
        decrypted = fernet.decrypt(path.read_bytes())
        return json.loads(decrypted)
    except (InvalidToken, json.JSONDecodeError, OSError):
        return None


def delete_session(domain: str) -> bool:
    """Remove session file. Returns True if deleted."""
    path = SESSIONS_DIR / f"{domain}.json.enc"
    if path.exists():
        path.unlink()
        return True
    return False


def session_exists(domain: str) -> bool:
    """Check if a session file exists for a domain."""
    return (SESSIONS_DIR / f"{domain}.json.enc").exists()
