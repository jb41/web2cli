"""Encrypted session storage.

Sessions are stored at ~/.web2cli/sessions/<domain>.json.enc
using Fernet symmetric encryption with a locally secured master key.
"""

import base64
import getpass
import hashlib
import json
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = Path(os.environ.get("WEB2CLI_DIR", Path.home() / ".web2cli"))
SESSIONS_DIR = BASE_DIR / "sessions"
KEY_FILE = BASE_DIR / ".master_key"
FIXED_SALT = b"web2cli-session-store-v1"


_DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,253}[a-zA-Z0-9])?$")


def sanitize_domain(domain: str) -> str:
    """Validate and sanitize a domain name or alias.

    Prevents path traversal, path injection, and invalid path characters.
    """
    clean = str(domain).strip().lower()
    if not _DOMAIN_PATTERN.match(clean) or ".." in clean or "/" in clean or "\\" in clean:
        raise ValueError(f"Invalid domain or alias identifier: {domain!r}")
    return clean


def _legacy_encryption_key() -> bytes:
    """Derive legacy key (fallback for migrating older sessions)."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "default"
    identity = f"{os.uname().nodename}:{user}:web2cli"
    dk = hashlib.pbkdf2_hmac("sha256", identity.encode(), FIXED_SALT, 100_000)
    return base64.urlsafe_b64encode(dk)


def _ensure_dir() -> None:
    """Ensure session directory exists with restrictive 0700 permissions."""
    for directory in (BASE_DIR, SESSIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass


def _get_encryption_key() -> bytes:
    """Retrieve or generate an isolated, cryptographically secure machine master key."""
    _ensure_dir()
    if KEY_FILE.is_file():
        try:
            key = KEY_FILE.read_bytes().strip()
            if len(key) == 44:  # Valid urlsafe base64 Fernet key length
                return key
        except OSError:
            pass

    new_key = Fernet.generate_key()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(KEY_FILE, flags, 0o600)
    try:
        with open(fd, "wb") as f:
            f.write(new_key)
    except Exception:
        os.close(fd)
        raise
    return new_key


def save_session(domain: str, data: dict) -> None:
    """Encrypt and persist session data for a domain atomically with mode 0600."""
    clean_domain = sanitize_domain(domain)
    _ensure_dir()
    fernet = Fernet(_get_encryption_key())
    encrypted = fernet.encrypt(json.dumps(data).encode("utf-8"))
    path = SESSIONS_DIR / f"{clean_domain}.json.enc"

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with open(fd, "wb") as f:
            f.write(encrypted)
    except Exception:
        os.close(fd)
        raise


def load_session(domain: str) -> dict | None:
    """Load and decrypt session for a domain. Returns None if missing/corrupt."""
    try:
        clean_domain = sanitize_domain(domain)
    except ValueError:
        return None

    path = SESSIONS_DIR / f"{clean_domain}.json.enc"
    if not path.is_file():
        return None
    try:
        raw_data = path.read_bytes()
        try:
            fernet = Fernet(_get_encryption_key())
            decrypted = fernet.decrypt(raw_data)
            return json.loads(decrypted)
        except InvalidToken:
            # Fallback to legacy key and upgrade session format if valid
            legacy_fernet = Fernet(_legacy_encryption_key())
            decrypted = legacy_fernet.decrypt(raw_data)
            session_dict = json.loads(decrypted)
            save_session(clean_domain, session_dict)
            return session_dict
    except (InvalidToken, json.JSONDecodeError, OSError):
        return None


def delete_session(domain: str) -> bool:
    """Remove session file. Returns True if deleted."""
    try:
        clean_domain = sanitize_domain(domain)
    except ValueError:
        return False
    path = SESSIONS_DIR / f"{clean_domain}.json.enc"
    if path.is_file():
        path.unlink()
        return True
    return False


def session_exists(domain: str) -> bool:
    """Check if a session file exists for a domain."""
    try:
        clean_domain = sanitize_domain(domain)
    except ValueError:
        return False
    return (SESSIONS_DIR / f"{clean_domain}.json.enc").is_file()

