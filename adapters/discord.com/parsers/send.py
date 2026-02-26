"""Custom parser for Discord send response.

Returns a single record confirming the sent message.
"""

import json
from datetime import datetime


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Parse the send-message response."""
    msg = json.loads(body)

    if not isinstance(msg, dict) or "id" not in msg:
        return []

    ts = msg.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts)
        ts = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        pass

    return [{
        "id": msg["id"],
        "content": msg.get("content", ""),
        "timestamp": ts,
        "channel_id": msg.get("channel_id", ""),
    }]
