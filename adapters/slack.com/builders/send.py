"""Custom builder for the 'send' command.

Resolves channel name → ID, then POST /chat.postMessage with token as form field.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import BASE_URL, _make_headers, _get_cookies, form_body, resolve_channel_id


def build(args: dict, session_dict: dict | None) -> Request:
    channel_name = args["channel"]
    message = args["message"]

    channel_id = resolve_channel_id(channel_name, session_dict)

    return Request(
        method="POST",
        url=f"{BASE_URL}/chat.postMessage",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body({"channel": channel_id, "text": message}, session_dict),
    )
