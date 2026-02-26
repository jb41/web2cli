"""Custom builder for the 'search' command.

Builds GraphQL SearchTimeline request with x-client-transaction-id.
"""

import json
import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from common import BASE_URL, FEATURES, make_headers
from resolve import get_query_id
from transaction import get_transaction_id


def build(args: dict, session_dict: dict | None) -> Request:
    query = args["query"]
    count = int(args.get("limit", 20))
    product = args.get("product", "Latest")

    query_id = get_query_id("SearchTimeline", force_refresh=args.get("_retry", False))
    url = f"{BASE_URL}/{query_id}/SearchTimeline"

    headers, cookies = make_headers(session_dict)
    headers["x-client-transaction-id"] = get_transaction_id("GET", url)

    return Request(
        method="GET",
        url=url,
        params={
            "variables": json.dumps({
                "rawQuery": query,
                "count": count,
                "querySource": "typed_query",
                "product": product,
            }),
            "features": json.dumps(FEATURES),
        },
        headers=headers,
        cookies=cookies,
    )
