"""Custom parser for Discord DM channels list."""

import json

# type 1 = DM, type 3 = Group DM
_TYPE_NAMES = {1: "DM", 3: "Group DM"}


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Parse DM channels response."""
    channels = json.loads(body)

    if not isinstance(channels, list):
        return []

    records = []
    for ch in channels:
        recipients = ch.get("recipients", [])
        names = [
            r.get("global_name") or r.get("username", "?")
            for r in recipients
        ]

        records.append({
            "id": ch.get("id", ""),
            "recipients": ", ".join(names),
            "type": _TYPE_NAMES.get(ch.get("type"), str(ch.get("type", "?"))),
            "last_message_id": ch.get("last_message_id", ""),
        })

    return records
