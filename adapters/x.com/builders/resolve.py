"""Resolve X.com GraphQL query IDs from the JS bundle with caching."""

import json
import re
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".web2cli" / "cache" / "x.com"
CACHE_FILE = "query_ids.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


def _fetch_query_ids() -> dict[str, str]:
    """Fetch main JS bundle from x.com and extract all query IDs.

    Returns dict: {operationName: queryId}
    """
    # Step 1: Fetch x.com to find the main JS bundle URL
    resp = httpx.get("https://x.com", headers={"User-Agent": UA}, follow_redirects=True)
    match = re.search(r'https://abs\.twimg\.com/responsive-web/client-web/main\.[a-f0-9]+\.js', resp.text)
    if not match:
        raise ValueError("Could not find main JS bundle URL on x.com")

    bundle_url = match.group(0)

    # Step 2: Fetch the JS bundle and extract query IDs
    resp = httpx.get(bundle_url, headers={"User-Agent": UA})
    pairs = re.findall(r'queryId:"([^"]+)",operationName:"([^"]+)"', resp.text)

    if not pairs:
        raise ValueError("Could not extract query IDs from JS bundle")

    mapping = {op_name: query_id for query_id, op_name in pairs}

    # Cache it
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / CACHE_FILE).write_text(json.dumps(mapping))

    return mapping


def _read_cache() -> dict[str, str] | None:
    path = CACHE_DIR / CACHE_FILE
    if path.is_file():
        return json.loads(path.read_text())
    return None


def get_query_id(operation_name: str, force_refresh: bool = False) -> str:
    """Get query ID for an operation, with cache + auto-refresh.

    1. Check cache
    2. If missing or force_refresh → fetch from JS bundle
    3. Return query ID or raise ValueError
    """
    if not force_refresh:
        cached = _read_cache()
        if cached and operation_name in cached:
            return cached[operation_name]

    # Fetch fresh
    mapping = _fetch_query_ids()

    if operation_name not in mapping:
        raise ValueError(
            f"Operation '{operation_name}' not found in X.com JS bundle. "
            f"Available: {', '.join(sorted(mapping.keys())[:20])}..."
        )

    return mapping[operation_name]
