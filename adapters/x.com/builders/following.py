"""Custom builder for the 'following' command.

Builds GraphQL HomeLatestTimeline request.
Recent = GET with enableRanking:false, Popular = POST with enableRanking:true.
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
    sort = args.get("sort", "recent")
    ranking = sort == "popular"

    query_id = get_query_id("HomeLatestTimeline", force_refresh=args.get("_retry", False))
    url = f"{BASE_URL}/{query_id}/HomeLatestTimeline"

    method = "POST" if ranking else "GET"
    headers, cookies = make_headers(session_dict)
    headers["x-client-transaction-id"] = get_transaction_id(method, url)

    variables = {
        "count": count,
        "enableRanking": ranking,
        "includePromotedContent": True,
    }

    if not ranking:
        variables["requestContext"] = "ptr"

    if ranking:
        return Request(
            method="POST",
            url=url,
            headers=headers,
            cookies=cookies,
            body={
                "variables": variables,
                "features": TIMELINE_FEATURES,
                "queryId": query_id,
            },
        )

    return Request(
        method="GET",
        url=url,
        params={
            "variables": json.dumps(variables),
            "features": json.dumps(TIMELINE_FEATURES),
        },
        headers=headers,
        cookies=cookies,
    )
