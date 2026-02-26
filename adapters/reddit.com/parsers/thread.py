"""Custom parser for Reddit thread (post + comments)."""

import json
from datetime import datetime, timezone


def _ts(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ""


def _walk_comments(children: list, records: list) -> None:
    """Recursively flatten comment tree into records list."""
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child.get("data", {})
        depth = c.get("depth", 0)
        indent = "  " * depth

        records.append({
            "depth": depth,
            "author": f"{indent}{c.get('author', '')}",
            "text": c.get("body", ""),
            "score": c.get("score", 0),
            "date": _ts(c.get("created_utc", 0)),
        })

        # Recurse into replies
        replies = c.get("replies")
        if isinstance(replies, dict):
            nested = replies.get("data", {}).get("children", [])
            _walk_comments(nested, records)


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    # Reddit returns [post_listing, comments_listing]
    if not isinstance(data, list) or len(data) < 2:
        return []

    records = []

    # First: the post itself
    post_children = data[0].get("data", {}).get("children", [])
    if post_children:
        p = post_children[0].get("data", {})
        text = p.get("selftext", "") or p.get("url", "")
        records.append({
            "author": p.get("author", ""),
            "text": f"[POST] {p.get('title', '')}\n{text}" if text else f"[POST] {p.get('title', '')}",
            "score": p.get("score", 0),
            "date": _ts(p.get("created_utc", 0)),
        })

    # Then: recursively walk all comments
    top_comments = data[1].get("data", {}).get("children", [])
    _walk_comments(top_comments, records)

    return records
