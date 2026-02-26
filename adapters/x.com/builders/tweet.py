"""Custom builder for the 'tweet' command.

Builds GraphQL TweetDetail request with all required params.
"""

import json
import re
from urllib.parse import quote

from web2cli.types import Request

BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
QUERY_ID = "zf_WcVlonaBUP8K7YK_PYQ"
BASE_URL = "https://x.com/i/api/graphql"

FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}


def _extract_tweet_id(raw: str) -> str:
    """Extract tweet ID from URL or return as-is if already an ID."""
    match = re.search(r"/status/(\d+)", raw)
    if match:
        return match.group(1)
    # Already a numeric ID
    if raw.strip().isdigit():
        return raw.strip()
    raise ValueError(f"Cannot extract tweet ID from: {raw}")


def build(args: dict, session_dict: dict | None) -> Request:
    tweet_id = _extract_tweet_id(args["id"])

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
    features = json.dumps(FEATURES)
    field_toggles = json.dumps(FIELD_TOGGLES)

    url = f"{BASE_URL}/{QUERY_ID}/TweetDetail"

    # x-csrf-token must match ct0 cookie
    ct0 = ""
    cookies = {}
    if session_dict and session_dict.get("cookies"):
        cookies = session_dict["cookies"]
        ct0 = cookies.get("ct0", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "authorization": BEARER,
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
    }

    return Request(
        method="GET",
        url=url,
        params={
            "variables": variables,
            "features": features,
            "fieldToggles": field_toggles,
        },
        headers=headers,
        cookies=cookies,
    )
