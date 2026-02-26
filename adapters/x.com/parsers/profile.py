"""Custom parser for X.com UserByScreenName GraphQL response."""

import json
from datetime import datetime


def _parse_date(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return raw or ""


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)
    user = data.get("data", {}).get("user", {}).get("result", {})

    if not user or user.get("__typename") not in ("User", None):
        if user.get("__typename") == "UserUnavailable":
            return [{"error": user.get("reason", "User unavailable")}]
        return []

    core = user.get("core", {})
    legacy = user.get("legacy", {})

    return [{
        "handle": f"@{core.get('screen_name', '')}",
        "name": core.get("name", ""),
        "bio": legacy.get("description", ""),
        "followers": legacy.get("followers_count", 0),
        "following": legacy.get("friends_count", 0),
        "tweets": legacy.get("statuses_count", 0),
        "likes": legacy.get("favourites_count", 0),
        "joined": _parse_date(core.get("created_at", "")),
        "verified": user.get("is_blue_verified", False),
        "location": legacy.get("location", ""),
        "url": f"https://x.com/{core.get('screen_name', '')}",
    }]
