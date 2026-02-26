"""Custom parser for Slack chat.postMessage response.

Shared by 'send' and 'dm-send' commands.
"""

import json
from datetime import datetime, timezone


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    if not data.get("ok"):
        return [{"ok": False, "error": data.get("error", "unknown")}]

    msg = data.get("message", {})
    ts = msg.get("ts", "")
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        ts_fmt = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        ts_fmt = ts

    return [{
        "ok": True,
        "channel": data.get("channel", ""),
        "timestamp": ts_fmt,
        "content": msg.get("text", ""),
    }]
