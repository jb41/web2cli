"""HTTP request execution via httpx."""

import sys
import time

import httpx

from web2cli.types import Request


class HttpError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


async def execute(
    request: Request, verbose: bool = False
) -> tuple[int, dict, str]:
    """Execute HTTP request. Returns (status_code, headers, body)."""
    if verbose:
        sys.stderr.write(f"→ {request.method} {request.url}\n")
        if request.params:
            sys.stderr.write(f"  params: {request.params}\n")

    start = time.monotonic()

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(
                method=request.method,
                url=request.url,
                params=request.params or None,
                headers=request.headers,
                cookies=request.cookies,
                content=request.body if isinstance(request.body, str) else None,
                json=request.body if isinstance(request.body, dict) else None,
            )
    except httpx.ConnectError:
        raise HttpError(0, f"Connection failed: could not reach {request.url}")
    except httpx.TimeoutException:
        raise HttpError(0, f"Request timed out: {request.url}")

    elapsed = time.monotonic() - start

    if verbose:
        sys.stderr.write(f"← {response.status_code} ({elapsed:.2f}s)\n")

    status = response.status_code

    if status == 429:
        retry = response.headers.get("Retry-After", "?")
        raise HttpError(429, f"Rate limited. Try again in {retry} seconds.")
    if status == 403:
        raise HttpError(
            403,
            "Access denied. You may need to login: web2cli login <domain>",
        )
    if status >= 500:
        raise HttpError(status, f"Server error ({status})")

    return status, dict(response.headers), response.text
