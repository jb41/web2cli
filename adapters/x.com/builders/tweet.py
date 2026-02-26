"""Custom builder for the 'tweet' command.

Builds GraphQL TweetDetail request with dynamic query ID.
"""

import json
import re
import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE_URL, FEATURES, FIELD_TOGGLES, make_headers
from resolve import get_query_id


def _extract_tweet_id(raw: str) -> str:
    """Extract tweet ID from URL or return as-is if already an ID."""
    match = re.search(r"/status/(\d+)", raw)
    if match:
        return match.group(1)
    if raw.strip().isdigit():
        return raw.strip()
    raise ValueError(f"Cannot extract tweet ID from: {raw}")


def build(args: dict, session_dict: dict | None) -> Request:
    tweet_id = _extract_tweet_id(args["id"])
    query_id = get_query_id("TweetDetail", force_refresh=args.get("_retry", False))

    variables = json.dumps({
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
    })

    headers, cookies = make_headers(session_dict)

    return Request(
        method="GET",
        url=f"{BASE_URL}/{query_id}/TweetDetail",
        params={
            "variables": variables,
            "features": json.dumps(FEATURES),
            "fieldToggles": json.dumps(FIELD_TOGGLES),
        },
        headers=headers,
        cookies=cookies,
    )
