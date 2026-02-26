"""Custom builder for the 'dm-messages' command.

Resolves user display name → DM channel ID,
then builds GET /channels/{id}/messages?limit=N.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import resolve_dm_channel_id, _make_headers

BASE_URL = "https://discord.com/api/v9"


def build(args: dict, session_dict: dict | None) -> Request:
    user_name = args["user"]
    limit = args.get("limit", 20)

    channel_id = resolve_dm_channel_id(user_name, session_dict)
    headers = _make_headers(session_dict)

    return Request(
        method="GET",
        url=f"{BASE_URL}/channels/{channel_id}/messages",
        params={"limit": str(limit)},
        headers=headers,
    )
