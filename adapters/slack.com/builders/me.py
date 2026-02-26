"""Custom builder for the 'me' command.

POST /auth.test with token as form field.
"""

import sys
from pathlib import Path

from web2cli.types import Request

sys.path.insert(0, str(Path(__file__).parent))
from resolve import BASE_URL, _make_headers, _get_cookies, form_body


def build(args: dict, session_dict: dict | None) -> Request:
    return Request(
        method="POST",
        url=f"{BASE_URL}/auth.test",
        headers=_make_headers(),
        cookies=_get_cookies(session_dict),
        body=form_body({}, session_dict),
    )
