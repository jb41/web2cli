"""Custom parser for Slack conversations.list (IM channels) response."""

import json


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    if not data.get("ok"):
        return []

    users_map = args.get("_users_map", {})
    records = []

    for ch in data.get("channels", []):
        user_id = ch.get("user", "")
        user_name = users_map.get(user_id, user_id)

        records.append({
            "user": user_name,
            "user_id": user_id,
            "id": ch.get("id", ""),
        })

    return records
