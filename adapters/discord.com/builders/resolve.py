"""Resolve Discord server/channel names to IDs with caching."""

import json
from pathlib import Path

import httpx

BASE_URL = "https://discord.com/api/v9"
CACHE_DIR = Path.home() / ".web2cli" / "cache" / "discord.com"


def _read_cache(filename: str) -> dict | list | None:
    path = CACHE_DIR / filename
    if path.is_file():
        return json.loads(path.read_text())
    return None


def _write_cache(filename: str, data: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / filename).write_text(json.dumps(data))


def _make_headers(session_dict: dict | None) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    if session_dict and session_dict.get("token"):
        headers["Authorization"] = session_dict["token"]
    return headers


def resolve_guild_id(server_name: str, session_dict: dict | None) -> str:
    """Resolve a server name to a guild ID.

    Checks cache first, then fetches from API and caches the result.
    Raises ValueError if the server is not found.
    """
    # Check cache
    guilds = _read_cache("guilds.json")
    if guilds:
        for g in guilds:
            if g["name"].lower() == server_name.lower():
                return g["id"]

    # Fetch from API
    headers = _make_headers(session_dict)
    resp = httpx.get(f"{BASE_URL}/users/@me/guilds", headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch guilds: HTTP {resp.status_code}")

    guilds = resp.json()
    _write_cache("guilds.json", guilds)

    for g in guilds:
        if g["name"].lower() == server_name.lower():
            return g["id"]

    available = ", ".join(g["name"] for g in guilds)
    raise ValueError(
        f"Server '{server_name}' not found. Available: {available}"
    )


def resolve_channel_id(
    guild_id: str, channel_name: str, session_dict: dict | None
) -> str:
    """Resolve a channel name to a channel ID within a guild.

    Checks cache first, then fetches from API and caches the result.
    Raises ValueError if the channel is not found.
    """
    cache_file = f"channels_{guild_id}.json"

    # Check cache
    channels = _read_cache(cache_file)
    if channels:
        for c in channels:
            if c.get("name", "").lower() == channel_name.lower():
                return c["id"]

    # Fetch from API
    headers = _make_headers(session_dict)
    resp = httpx.get(f"{BASE_URL}/guilds/{guild_id}/channels", headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch channels: HTTP {resp.status_code}")

    channels = resp.json()
    _write_cache(cache_file, channels)

    for c in channels:
        if c.get("name", "").lower() == channel_name.lower():
            return c["id"]

    # Show only text channels (type 0) in error
    text_channels = [c["name"] for c in channels if c.get("type") == 0]
    available = ", ".join(text_channels)
    raise ValueError(
        f"Channel '{channel_name}' not found. Text channels: {available}"
    )


def resolve_dm_channel_id(user_name: str, session_dict: dict | None) -> str:
    """Resolve a user display name to a DM channel ID.

    Checks cache first, then fetches from API and caches the result.
    Matches against global_name and username (case-insensitive).
    Raises ValueError if the user is not found.
    """
    cache_file = "dm_channels.json"

    def _find(channels: list) -> str | None:
        for ch in channels:
            if ch.get("type") not in (1, 3):  # DM or Group DM
                continue
            for r in ch.get("recipients", []):
                name = r.get("global_name") or r.get("username", "")
                if name.lower() == user_name.lower():
                    return ch["id"]
        return None

    # Check cache
    cached = _read_cache(cache_file)
    if cached:
        found = _find(cached)
        if found:
            return found

    # Fetch from API
    headers = _make_headers(session_dict)
    resp = httpx.get(f"{BASE_URL}/users/@me/channels", headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch DM channels: HTTP {resp.status_code}")

    channels = resp.json()
    _write_cache(cache_file, channels)

    found = _find(channels)
    if found:
        return found

    # List available DM recipients for error message
    all_names = []
    for ch in channels:
        for r in ch.get("recipients", []):
            all_names.append(r.get("global_name") or r.get("username", "?"))
    available = ", ".join(all_names)
    raise ValueError(
        f"No DM with '{user_name}' found. Available: {available}"
    )
