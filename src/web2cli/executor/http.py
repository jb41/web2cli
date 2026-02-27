"""HTTP request execution via httpx (default) or curl_cffi (TLS impersonation)."""

import sys
import time

import httpx

from web2cli.types import Request


class HttpError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


async def _execute_httpx(request: Request) -> tuple[int, dict, str]:
    """Execute via httpx (standard path)."""
    content_type = (request.content_type or request.headers.get("Content-Type", "")).lower()
    body_is_form = (
        isinstance(request.body, dict)
        and content_type.startswith("application/x-www-form-urlencoded")
    )

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(
                method=request.method,
                url=request.url,
                params=request.params or None,
                headers=request.headers,
                cookies=request.cookies,
                content=request.body if isinstance(request.body, (str, bytes)) else None,
                data=request.body if body_is_form else None,
                json=request.body if isinstance(request.body, dict) and not body_is_form else None,
            )
    except httpx.ConnectError:
        raise HttpError(0, f"Connection failed: could not reach {request.url}")
    except httpx.TimeoutException:
        raise HttpError(0, f"Request timed out: {request.url}")

    return response.status_code, dict(response.headers), response.text


async def _execute_impersonate(
    request: Request, impersonate: str
) -> tuple[int, dict, str]:
    """Execute via curl_cffi with TLS impersonation."""
    from curl_cffi.requests import AsyncSession

    content_type = (request.content_type or request.headers.get("Content-Type", "")).lower()
    body_is_form = (
        isinstance(request.body, dict)
        and content_type.startswith("application/x-www-form-urlencoded")
    )

    try:
        async with AsyncSession(impersonate=impersonate) as session:
            response = await session.request(
                method=request.method,
                url=request.url,
                params=request.params or None,
                headers=request.headers,
                cookies=request.cookies,
                data=request.body if body_is_form else (
                    request.body if isinstance(request.body, (str, bytes)) else None
                ),
                json=request.body if isinstance(request.body, dict) and not body_is_form else None,
                allow_redirects=True,
            )
    except ConnectionError:
        raise HttpError(0, f"Connection failed: could not reach {request.url}")
    except TimeoutError:
        raise HttpError(0, f"Request timed out: {request.url}")

    return response.status_code, dict(response.headers), response.text


async def execute(
    request: Request, verbose: bool = False, impersonate: str | None = None
) -> tuple[int, dict, str]:
    """Execute HTTP request. Returns (status_code, headers, body)."""
    if verbose:
        sys.stderr.write(f"→ {request.method} {request.url}\n")
        if request.params:
            sys.stderr.write(f"  params: {request.params}\n")
        if impersonate:
            sys.stderr.write(f"  impersonate: {impersonate}\n")

    start = time.monotonic()

    if impersonate:
        status, headers, body = await _execute_impersonate(request, impersonate)
    else:
        status, headers, body = await _execute_httpx(request)

    elapsed = time.monotonic() - start

    if verbose:
        sys.stderr.write(f"← {status} ({elapsed:.2f}s)\n")

    if status == 429:
        retry = headers.get("Retry-After", "?")
        raise HttpError(429, f"Rate limited. Try again in {retry} seconds.")
    if status == 403:
        raise HttpError(
            403,
            "Access denied. You may need to login: web2cli login <domain>",
        )
    if status >= 500:
        raise HttpError(status, f"Server error ({status})")

    return status, headers, body
