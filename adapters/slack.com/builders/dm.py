"""Custom builder for the 'dm' command.

Injects users_map for parser, then POST /conversations.list with types=im.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import BASE_URL, _make_headers, _get_cookies, form_body, resolve_users


def build(args: dict, session_dict: dict | None) -> Request:
    args["_users_map"] = resolve_users(session_dict)

    return Request(
        method="POST",
        url=f"{BASE_URL}/conversations.list",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body({"types": "im", "limit": "200"}, session_dict),
    )
