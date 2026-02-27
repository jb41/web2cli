"""Small file cache for v0.2 resources."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

BASE_CACHE_DIR = Path.home() / ".web2cli" / "cache"


def _cache_path(domain: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()  # nosec: non-crypto use
    return BASE_CACHE_DIR / domain / "v2" / f"{digest}.json"


def load_cache(domain: str, key: str, ttl: int | None = None) -> Any | None:
    """Load cached payload if present and not expired."""
    path = _cache_path(domain, key)
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
    path = _cache_path(domain, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"ts": time.time(), "payload": payload}
    path.write_text(json.dumps(doc))

