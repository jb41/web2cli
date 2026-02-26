"""Custom builder for the 'dm-messages' command.

Resolves user name → DM channel ID, injects users_map for parser,
then POST /conversations.history with token as form field.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import (
    BASE_URL,
    _make_headers,
    _get_cookies,
    form_body,
    resolve_dm_channel_id,
    resolve_users,
)


def build(args: dict, session_dict: dict | None) -> Request:
    user_name = args["user"]
    limit = args.get("limit", 20)

    channel_id = resolve_dm_channel_id(user_name, session_dict)
    args["_users_map"] = resolve_users(session_dict)

    return Request(
        method="POST",
        url=f"{BASE_URL}/conversations.history",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body({"channel": channel_id, "limit": str(limit)}, session_dict),
    )
