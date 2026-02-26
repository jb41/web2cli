"""Custom parser for X.com HomeTimeline / HomeLatestTimeline responses."""

import json
from datetime import datetime


def _parse_date(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return raw or ""


def _extract_tweet(result: dict) -> dict | None:
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})
    if result.get("__typename") != "Tweet":
        return None

    legacy = result.get("legacy", {})
    user_result = result.get("core", {}).get("user_results", {}).get("result", {})

    user_core = user_result.get("core", {})
    screen_name = user_core.get("screen_name", "")
    name = user_core.get("name", "")

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
        "url": f"https://x.com/{screen_name}/status/{legacy.get('id_str', '')}",
    }


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    data = json.loads(body)

    # HomeTimeline and HomeLatestTimeline share the same response structure
    timeline = (
        data.get("data", {})
        .get("home", {})
        .get("home_timeline_urt", {})
    )

    tweets = []
    for inst in timeline.get("instructions", []):
        for entry in inst.get("entries", []):
            result = (
                entry.get("content", {})
                .get("itemContent", {})
                .get("tweet_results", {})
                .get("result", {})
            )
            tweet = _extract_tweet(result)
            if tweet:
                tweets.append(tweet)

    return tweets
