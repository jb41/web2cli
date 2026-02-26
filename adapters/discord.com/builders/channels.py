"""Custom builder for the 'channels' command.

Resolves server name → guild ID, then builds GET /guilds/{id}/channels.
"""

import sys
from pathlib import Path

from web2cli.types import Request

# Import resolve from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from resolve import resolve_guild_id, _make_headers

BASE_URL = "https://discord.com/api/v9"


def build(args: dict, session_dict: dict | None) -> Request:
    server_name = args["server"]
    guild_id = resolve_guild_id(server_name, session_dict)
    headers = _make_headers(session_dict)

    return Request(
        method="GET",
        url=f"{BASE_URL}/guilds/{guild_id}/channels",
        headers=headers,
    )
