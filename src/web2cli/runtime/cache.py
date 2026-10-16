"""Small file cache for runtime resources."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from web2cli.auth.store import sanitize_domain

import os

BASE_CACHE_DIR = Path(os.environ.get("WEB2CLI_CACHE_DIR", Path.home() / ".web2cli" / "cache"))



def _cache_path(domain: str, key: str) -> Path:
    clean_domain = sanitize_domain(domain)
    digest = hashlib.sha1(key.encode()).hexdigest()  # nosec: non-crypto use
    path = BASE_CACHE_DIR / clean_domain / "runtime" / f"{digest}.json"
    if not path.resolve().is_relative_to(BASE_CACHE_DIR.resolve()):
        raise ValueError(f"Cache path traversal detected for domain {domain!r}")
    return path


def load_cache(domain: str, key: str, ttl: int | None = None) -> Any | None:
    """Load cached payload if present and not expired."""
    try:
        path = _cache_path(domain, key)
    except ValueError:
        return None

    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    ts = data.get("ts")
    if ttl and isinstance(ts, (int, float)):
        if time.time() - ts > ttl:
            return None

    return data.get("payload")


def save_cache(domain: str, key: str, payload: Any) -> None:
    """Persist payload in cache."""
    try:
        path = _cache_path(domain, key)
    except ValueError:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"ts": time.time(), "payload": payload}
    path.write_text(json.dumps(doc))

