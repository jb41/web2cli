"""Custom parser for X.com TweetDetail GraphQL response."""

import json
from datetime import datetime


def _parse_date(raw: str) -> str:
    """Convert Twitter date format to readable."""
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return raw or ""


def _extract_tweet(result: dict) -> dict | None:
    """Extract tweet data from a result object."""
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})
    if result.get("__typename") != "Tweet":
        return None

    legacy = result.get("legacy", {})
    user_result = result.get("core", {}).get("user_results", {}).get("result", {})

    # screen_name moved to user_result.core in newer API
    user_core = user_result.get("core", {})
    screen_name = user_core.get("screen_name", "")
    name = user_core.get("name", "")

    # Fallback to legacy path
    if not screen_name:
        user_legacy = user_result.get("legacy", {})
        screen_name = user_legacy.get("screen_name", "")
        name = user_legacy.get("name", "")

    return {
        "id": legacy.get("id_str", ""),
        "author": f"@{screen_name}" if screen_name else "?",
        "name": name,
        "text": legacy.get("full_text", ""),
        "date": _parse_date(legacy.get("created_at", "")),
        "retweets": legacy.get("retweet_count", 0),
        "likes": legacy.get("favorite_count", 0),
        "replies": legacy.get("reply_count", 0),
        "views": result.get("views", {}).get("count", ""),
        "bookmarks": legacy.get("bookmark_count", 0),
        "url": f"https://x.com/{screen_name}/status/{legacy.get('id_str', '')}",
    }


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Parse TweetDetail response — returns the focal tweet."""
    data = json.loads(body)

    instructions = (
        data.get("data", {})
        .get("threaded_conversation_with_injections_v2", {})
        .get("instructions", [])
    )

    for inst in instructions:
        for entry in inst.get("entries", []):
            result = (
                entry.get("content", {})
                .get("itemContent", {})
                .get("tweet_results", {})
                .get("result", {})
            )
            tweet = _extract_tweet(result)
            if tweet:
                return [tweet]

    return []
