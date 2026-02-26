"""Custom parser for Discord messages.

Formats message data with author, content, timestamp, and reactions.
"""

import json
from datetime import datetime


def _format_timestamp(iso_str: str) -> str:
    """Convert ISO timestamp to a readable format."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("+00:00", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso_str


def _format_reactions(reactions: list | None) -> str:
    """Format reactions as 'emoji xN' string."""
    if not reactions:
        return ""
    parts = []
    for r in reactions:
        emoji = r.get("emoji", {})
        name = emoji.get("name", "?")
        count = r.get("count", 1)
        parts.append(f"{name} x{count}" if count > 1 else name)
    return " ".join(parts)


def _format_attachment_urls(attachments: list) -> str:
    """Extract URLs from attachments."""
    return " ".join(a["url"] for a in attachments if a.get("url"))


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Parse Discord messages response."""
    messages = json.loads(body)

    if not isinstance(messages, list):
        return []

    show_attachments = not args.get("no_attachments", False)

    records = []
    for msg in messages:
        author_info = msg.get("author", {})
        author = author_info.get("global_name") or author_info.get("username", "?")

        content = msg.get("content", "")

        # Append attachment URLs to content
        if show_attachments and msg.get("attachments"):
            urls = _format_attachment_urls(msg["attachments"])
            if urls:
                content = f"{content} {urls}" if content else urls

        records.append({
            "author": author,
            "content": content,
            "timestamp": _format_timestamp(msg.get("timestamp", "")),
            "reactions": _format_reactions(msg.get("reactions")),
            "type": msg.get("type", 0),
            "id": msg.get("id", ""),
            "embeds": len(msg.get("embeds", [])),
        })

    # Messages come newest-first from API; reverse for chronological order
    records.reverse()
    return records
