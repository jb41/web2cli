"""Custom builder for the 'messages' command.

Resolves server name → guild ID → channel name → channel ID,
then builds GET /channels/{id}/messages?limit=N.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import resolve_guild_id, resolve_channel_id, _make_headers

BASE_URL = "https://discord.com/api/v9"


def build(args: dict, session_dict: dict | None) -> Request:
    server_name = args["server"]
    channel_name = args["channel"]
    limit = args.get("limit", 20)

    guild_id = resolve_guild_id(server_name, session_dict)
    channel_id = resolve_channel_id(guild_id, channel_name, session_dict)
    headers = _make_headers(session_dict)

    return Request(
        method="GET",
        url=f"{BASE_URL}/channels/{channel_id}/messages",
        params={"limit": str(limit)},
        headers=headers,
    )
