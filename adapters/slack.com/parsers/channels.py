"""Custom parser for Slack conversations.list (channels) response."""

import json


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    if not data.get("ok"):
        return []

    records = []
    for ch in data.get("channels", []):
        records.append({
            "id": ch.get("id", ""),
            "name": ch.get("name", ""),
            "topic": ch.get("topic", {}).get("value", ""),
            "purpose": ch.get("purpose", {}).get("value", ""),
            "num_members": ch.get("num_members", 0),
            "is_private": ch.get("is_private", False),
        })

    return records
