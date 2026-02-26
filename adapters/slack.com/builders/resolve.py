"""Resolve Slack channel/user names to IDs with caching.

Slack xoxc- tokens are sent as a form field (not Authorization header),
together with the `d` cookie from the browser session.
"""

import json
from pathlib import Path
from urllib.parse import urlencode

import httpx

BASE_URL = "https://slack.com/api"
CACHE_DIR = Path.home() / ".web2cli" / "cache" / "slack.com"


def _read_cache(filename: str) -> dict | list | None:
    path = CACHE_DIR / filename
    if path.is_file():
        return json.loads(path.read_text())
    return None


def _write_cache(filename: str, data: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / filename).write_text(json.dumps(data))


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _get_cookies(session_dict: dict | None) -> dict:
    if session_dict and session_dict.get("cookies"):
        return session_dict["cookies"]
    return {}


def _get_token(session_dict: dict | None) -> str:
    if session_dict and session_dict.get("token"):
        return session_dict["token"]
    return ""


def form_body(params: dict, session_dict: dict | None) -> str:
    """Build URL-encoded form body with token injected."""
    token = _get_token(session_dict)
    if token:
        params["token"] = token
    return urlencode(params)


def _slack_post(endpoint: str, body: dict, session_dict: dict | None) -> dict:
    """POST to Slack API with form-encoded body. Raises on error."""
    headers = _make_headers()
    cookies = _get_cookies(session_dict)
    # Inject token into form fields
    token = _get_token(session_dict)
    if token:
        body["token"] = token
    resp = httpx.post(
        f"{BASE_URL}/{endpoint}",
        headers=headers,
        cookies=cookies,
        data=body,
    )
    if resp.status_code != 200:
        raise ValueError(f"Slack API error: HTTP {resp.status_code}")
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"Slack API error: {data.get('error', 'unknown')}")
    return data


def resolve_users(session_dict: dict | None) -> dict[str, str]:
    """Resolve all workspace users to {user_id: display_name}.

    Uses cursor-based pagination. Caches result.
    """
    cached = _read_cache("users.json")
    if cached:
        return cached

    users_map = {}
    cursor = None

    while True:
        body = {"limit": 200}
        if cursor:
            body["cursor"] = cursor

        data = _slack_post("users.list", body, session_dict)

        for member in data.get("members", []):
            uid = member["id"]
            profile = member.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or member.get("real_name")
                or member.get("name", uid)
            )
            users_map[uid] = name

        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break

    _write_cache("users.json", users_map)
    return users_map


def resolve_channel_id(name: str, session_dict: dict | None) -> str:
    """Resolve a channel name to its ID.

    Checks cache first, then fetches public + private channels.
    Raises ValueError if not found.
    """
    cached = _read_cache("channels.json")
    if cached:
        for ch in cached:
            if ch["name"].lower() == name.lower():
                return ch["id"]

    # Fetch all channels (public + private)
    channels = []
    cursor = None

    while True:
        body = {"types": "public_channel,private_channel", "limit": 200}
        if cursor:
            body["cursor"] = cursor

        data = _slack_post("conversations.list", body, session_dict)

        for ch in data.get("channels", []):
            channels.append({
                "id": ch["id"],
                "name": ch.get("name", ""),
                "topic": ch.get("topic", {}).get("value", ""),
                "num_members": ch.get("num_members", 0),
            })

        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break

    _write_cache("channels.json", channels)

    for ch in channels:
        if ch["name"].lower() == name.lower():
            return ch["id"]

    available = ", ".join(ch["name"] for ch in channels[:30])
    raise ValueError(f"Channel '{name}' not found. Available: {available}")


def resolve_user_id(name: str, session_dict: dict | None) -> str:
    """Resolve a user display name to user ID.

    Matches against display_name, real_name, or username (case-insensitive).
    """
    users_map = resolve_users(session_dict)

    for uid, display_name in users_map.items():
        if display_name.lower() == name.lower():
            return uid

    available = ", ".join(list(users_map.values())[:30])
    raise ValueError(f"User '{name}' not found. Available: {available}")


def resolve_dm_channel_id(user_name: str, session_dict: dict | None) -> str:
    """Resolve a user name to a DM channel ID.

    Checks cache, then fetches IM conversations and matches user.
    """
    user_id = resolve_user_id(user_name, session_dict)

    cached = _read_cache("dm_channels.json")
    if cached:
        for dm in cached:
            if dm.get("user") == user_id:
                return dm["id"]

    # Fetch IM channels
    dm_channels = []
    cursor = None

    while True:
        body = {"types": "im", "limit": 200}
        if cursor:
            body["cursor"] = cursor

        data = _slack_post("conversations.list", body, session_dict)

        for ch in data.get("channels", []):
            dm_channels.append({
                "id": ch["id"],
                "user": ch.get("user", ""),
            })

        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break

    _write_cache("dm_channels.json", dm_channels)

    for dm in dm_channels:
        if dm.get("user") == user_id:
            return dm["id"]

    raise ValueError(f"No DM channel with '{user_name}' found. Try sending a DM in Slack first.")
