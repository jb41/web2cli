"""Generate x-client-transaction-id for X.com API requests.

Uses the XClientTransaction library to reverse-engineer the browser's
cryptographic nonce. Requires 2 HTTP fetches on first call (home page +
ondemand.s JS file), then generates IDs instantly.
"""

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import get_ondemand_file_url

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

_ct: ClientTransaction | None = None


def _init() -> ClientTransaction:
    global _ct
    if _ct is not None:
        return _ct

    headers = {"User-Agent": UA}

    # 1. Fetch x.com home page
    home_resp = httpx.get("https://x.com", headers=headers, follow_redirects=True)
    home_soup = BeautifulSoup(home_resp.text, "html.parser")

    # 2. Extract ondemand.s file URL and fetch it
    ondemand_url = get_ondemand_file_url(response=home_soup)
    ondemand_resp = httpx.get(ondemand_url, headers=headers)

    # 3. Create ClientTransaction (accepts str for ondemand file)
    _ct = ClientTransaction(
        home_page_response=home_soup,
        ondemand_file_response=ondemand_resp.text,
    )
    return _ct


def get_transaction_id(method: str, url: str) -> str:
    """Generate a one-time x-client-transaction-id for the given request."""
    ct = _init()
    path = urlparse(url).path
    return ct.generate_transaction_id(method=method, path=path)
