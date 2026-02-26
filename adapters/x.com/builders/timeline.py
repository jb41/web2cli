"""Custom builder for the 'timeline' command (For you tab).

Builds GraphQL HomeTimeline request with x-client-transaction-id.
"""

import json
import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE_URL, TIMELINE_FEATURES, make_headers
from resolve import get_query_id
from transaction import get_transaction_id


def build(args: dict, session_dict: dict | None) -> Request:
    count = int(args.get("limit", 20))

    query_id = get_query_id("HomeTimeline", force_refresh=args.get("_retry", False))
    url = f"{BASE_URL}/{query_id}/HomeTimeline"

    headers, cookies = make_headers(session_dict)
    headers["x-client-transaction-id"] = get_transaction_id("GET", url)

    return Request(
        method="GET",
        url=url,
        params={
            "variables": json.dumps({
                "count": count,
                "includePromotedContent": True,
                "requestContext": "launch",
                "withCommunity": True,
            }),
            "features": json.dumps(TIMELINE_FEATURES),
        },
        headers=headers,
        cookies=cookies,
    )
