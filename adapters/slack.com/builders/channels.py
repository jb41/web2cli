"""Custom builder for the 'channels' command.

POST /conversations.list with types=public_channel,private_channel.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import BASE_URL, _make_headers, _get_cookies, form_body


def build(args: dict, session_dict: dict | None) -> Request:
    return Request(
        method="POST",
        url=f"{BASE_URL}/conversations.list",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body(
            {"types": "public_channel,private_channel", "limit": "200"},
            session_dict,
        ),
    )
