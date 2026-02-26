"""Custom builder for the 'dm-send' command.

Resolves user display name → DM channel ID,
then builds POST /channels/{id}/messages with JSON body.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import resolve_dm_channel_id, _make_headers

BASE_URL = "https://discord.com/api/v9"


def build(args: dict, session_dict: dict | None) -> Request:
    user_name = args["user"]
    message = args["message"]

    channel_id = resolve_dm_channel_id(user_name, session_dict)
    headers = _make_headers(session_dict)
    headers["Content-Type"] = "application/json"

    return Request(
        method="POST",
        url=f"{BASE_URL}/channels/{channel_id}/messages",
        headers=headers,
        body={"content": message},
    )
