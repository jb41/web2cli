"""Custom builder for the 'send' command.

Resolves server + channel names → channel ID,
then builds POST /channels/{id}/messages with JSON body.
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
    message = args["message"]

    guild_id = resolve_guild_id(server_name, session_dict)
    channel_id = resolve_channel_id(guild_id, channel_name, session_dict)
    headers = _make_headers(session_dict)
    headers["Content-Type"] = "application/json"

    return Request(
        method="POST",
        url=f"{BASE_URL}/channels/{channel_id}/messages",
        headers=headers,
        body={"content": message},
    )
