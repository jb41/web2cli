"""Custom builder for the 'profile' command.

Builds GraphQL UserByScreenName request.
"""

import json
import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE_URL, make_headers
from resolve import get_query_id

FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}


def build(args: dict, session_dict: dict | None) -> Request:
    screen_name = args["user"].lstrip("@")
    query_id = get_query_id("UserByScreenName", force_refresh=args.get("_retry", False))

    headers, cookies = make_headers(session_dict)

    return Request(
        method="GET",
        url=f"{BASE_URL}/{query_id}/UserByScreenName",
        params={
            "variables": json.dumps({
                "screen_name": screen_name,
                "withSafetyModeUserFields": True,
            }),
            "features": json.dumps(FEATURES),
        },
        headers=headers,
        cookies=cookies,
    )
