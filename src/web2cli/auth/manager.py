"""Session management — create, get, remove, check.

Handles cookie parsing, env var fallback, and persistence via store.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from web2cli.auth.store import (
    delete_session,
    load_session,
    save_session,
    session_exists,
)
from web2cli.types import Session


def parse_cookie_string(raw: str) -> dict[str, str]:
    """Parse "k=v; k2=v2" into dict."""
    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" in pair:
            key, _, value = pair.partition("=")
            cookies[key.strip()] = value.strip()
    return cookies


def parse_cookie_file(path: str) -> dict[str, str]:
    """Load a JSON file as cookie dict."""
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Cookie file must contain a JSON object, got {type(data).__name__}")
    return {str(k): str(v) for k, v in data.items()}


def create_session(
    domain: str,
    cookies: dict[str, str] | None = None,
    token: str | None = None,
) -> Session:
    """Create and persist a session."""
    now = datetime.now(timezone.utc).isoformat()

    if cookies:
        auth_type = "cookies"
        data = {"cookies": cookies}
    elif token:
        auth_type = "token"
        data = {"token": token}
    else:
        raise ValueError("Either cookies or token must be provided")

    session = Session(
        domain=domain,
        auth_type=auth_type,
        data=data,
        created_at=now,
        last_used=now,
    )

    save_session(domain, {
        "domain": session.domain,
        "auth_type": session.auth_type,
        "data": session.data,
        "created_at": session.created_at,
        "last_used": session.last_used,
    })

    return session


def get_session(domain: str, auth_spec: dict | None = None) -> Session | None:
    """Retrieve session for a domain.

    Checks env var first (from auth_spec), then stored session file.
    """
    # Env var fallback
    if auth_spec:
        for method in auth_spec.get("methods", []):
            env_var = method.get("env_var")
            if env_var:
                env_val = os.environ.get(env_var)
                if env_val:
                    cookies = parse_cookie_string(env_val)
                    return Session(
                        domain=domain,
                        auth_type="cookies",
                        data={"cookies": cookies},
                    )

    # Stored session
    raw = load_session(domain)
    if raw is None:
        return None

    return Session(
        domain=raw.get("domain", domain),
        auth_type=raw.get("auth_type", "cookies"),
        data=raw.get("data", {}),
        created_at=raw.get("created_at", ""),
        last_used=raw.get("last_used", ""),
    )


def remove_session(domain: str) -> bool:
    """Remove stored session."""
    return delete_session(domain)


def check_session(domain: str) -> dict:
    """Return session metadata (no secrets). For --status display."""
    if not session_exists(domain):
        return {"exists": False}

    raw = load_session(domain)
    if raw is None:
        return {"exists": False, "error": "corrupt or unreadable"}

    info = {
        "exists": True,
        "auth_type": raw.get("auth_type", "unknown"),
        "created_at": raw.get("created_at", ""),
        "last_used": raw.get("last_used", ""),
    }

    # Show cookie key names (not values) for verification
    data = raw.get("data", {})
    if "cookies" in data:
        info["cookie_keys"] = list(data["cookies"].keys())
    if "token" in data:
        info["has_token"] = True

    return info
