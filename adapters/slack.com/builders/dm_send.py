"""Custom builder for the 'dm-send' command.

Resolves user name → DM channel ID, then POST /chat.postMessage with token as form field.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import BASE_URL, _make_headers, _get_cookies, form_body, resolve_dm_channel_id


def build(args: dict, session_dict: dict | None) -> Request:
    user_name = args["user"]
    message = args["message"]

    channel_id = resolve_dm_channel_id(user_name, session_dict)

    return Request(
        method="POST",
        url=f"{BASE_URL}/chat.postMessage",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body({"channel": channel_id, "text": message}, session_dict),
    )
