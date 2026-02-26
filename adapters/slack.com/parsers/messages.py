"""Custom parser for Slack conversations.history response.

Shared by 'messages' and 'dm-messages' commands.
Uses _users_map from args to resolve user IDs to display names.
"""

import json
from datetime import datetime, timezone


def _format_timestamp(ts: str) -> str:
    """Convert Slack epoch timestamp to readable format."""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ts


def _format_reactions(reactions: list | None) -> str:
    """Format reactions as 'emoji xN' string."""
    if not reactions:
        return ""
    parts = []
    for r in reactions:
        name = r.get("name", "?")
        count = r.get("count", 1)
        parts.append(f":{name}: x{count}" if count > 1 else f":{name}:")
    return " ".join(parts)


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    if not data.get("ok"):
        return []

    users_map = args.get("_users_map", {})
    messages = data.get("messages", [])

    records = []
    for msg in messages:
        user_id = msg.get("user", "")
        author = users_map.get(user_id, user_id)

        # Handle bot messages
        if msg.get("subtype") == "bot_message":
            author = msg.get("username") or msg.get("bot_id", "bot")

        content = msg.get("text", "")

        # Resolve <@U123> mentions in content
        if users_map and "<@" in content:
            for uid, uname in users_map.items():
                content = content.replace(f"<@{uid}>", f"@{uname}")

        records.append({
            "author": author,
            "content": content,
            "timestamp": _format_timestamp(msg.get("ts", "")),
            "reactions": _format_reactions(msg.get("reactions")),
            "type": msg.get("subtype", "message"),
            "ts": msg.get("ts", ""),
        })

    # Messages come newest-first; reverse for chronological order
    records.reverse()
    return records
