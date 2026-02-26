"""Custom parser for Slack auth.test response."""

import json


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    if not data.get("ok"):
        return [{"error": data.get("error", "unknown")}]

    return [{
        "user_id": data.get("user_id", ""),
        "user": data.get("user", ""),
        "team_id": data.get("team_id", ""),
        "team": data.get("team", ""),
        "url": data.get("url", ""),
    }]
