"""Browser-assisted auth capture for login command."""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from dataclasses import dataclass
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse


class BrowserLoginError(RuntimeError):
    """Raised for browser-login failures."""


class BrowserLoginCancelled(RuntimeError):
    """Raised when user cancels browser login."""


@dataclass(frozen=True)
class TokenCaptureRule:
    """Declarative rule for extracting token from browser network requests."""

    source: str  # request.header | request.form
    key: str
    host: str | None = None
    path_regex: str | None = None
    method: str | None = None
    strip_prefix: str | None = None


def _emit(status_cb: Callable[[str], None] | None, message: str) -> None:
    if status_cb:
        status_cb(message)


def _emit_debug(debug_cb: Callable[[str], None] | None, message: str) -> None:
    if debug_cb:
        debug_cb(message)


def _run_command(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return
    detail = (proc.stderr or proc.stdout or "").strip()
    raise BrowserLoginError(
        f"Command failed: {' '.join(cmd)}"
        + (f"\n{detail}" if detail else "")
    )


def _ensure_playwright_package(status_cb: Callable[[str], None] | None):
    try:
        from playwright import async_api as playwright_async_api

        return playwright_async_api
    except Exception:
        _emit(status_cb, "Installing Playwright Python package...")
        _run_command([sys.executable, "-m", "pip", "install", "playwright"])
        try:
            from playwright import async_api as playwright_async_api

            return playwright_async_api
        except Exception as e:
            raise BrowserLoginError(f"Failed to import Playwright after install: {e}")


def _is_missing_browser_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "executable doesn't exist" in text
        or ("playwright install" in text and "chromium" in text)
    )


def _install_chromium(status_cb: Callable[[str], None] | None) -> None:
    _emit(status_cb, "Installing browser engine (one-time, ~50MB)...")
    _run_command([sys.executable, "-m", "playwright", "install", "chromium"])


def _header_value(headers: dict[str, str], key: str) -> str | None:
    wanted = key.lower()
    for hkey, hval in headers.items():
        if str(hkey).lower() == wanted:
            return str(hval)
    return None


def _multipart_form_value(post_data: str, key: str) -> str | None:
    lines = post_data.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if not first.startswith("--") or len(first) <= 2:
        return None
    boundary = first[2:]
    delimiter = f"--{boundary}"

    for raw_part in post_data.split(delimiter):
        part = raw_part.strip()
        if not part or part == "--":
            continue
        if part.endswith("--"):
            part = part[:-2].rstrip()

        header_blob, sep, body = part.partition("\r\n\r\n")
        if not sep:
            header_blob, sep, body = part.partition("\n\n")
        if not sep:
            continue

        header_lines = [h.strip() for h in header_blob.splitlines() if h.strip()]
        disposition = ""
        for line in header_lines:
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        if not disposition:
            continue

        needle = f'name="{key}"'
        if needle not in disposition:
            continue

        value = body.strip("\r\n")
        return value or None
    return None


def _form_value(post_data: str, key: str) -> str | None:
    parsed = parse_qs(post_data, keep_blank_values=True)
    values = parsed.get(key)
    if values:
        value = values[0]
        if value is not None:
            return str(value)

    # Fallback for multipart/form-data payloads.
    return _multipart_form_value(post_data, key)


def _request_headers_safe(request) -> dict[str, str]:
    try:
        raw_headers = request.headers
    except Exception:
        return {}
    if callable(raw_headers):
        try:
            raw_headers = raw_headers()
        except Exception:
            return {}
    if isinstance(raw_headers, dict):
        return dict(raw_headers)
    return {}


def _request_post_data_safe(request) -> str:
    # Prefer raw bytes if exposed by current Playwright version.
    try:
        raw_post_data = request.post_data_buffer
        if callable(raw_post_data):
            raw_post_data = raw_post_data()
        if isinstance(raw_post_data, (bytes, bytearray)):
            return bytes(raw_post_data).decode("utf-8", errors="ignore")
    except Exception:
        pass

    # Fallback to decoded post_data; some requests can raise decode errors.
    try:
        raw_post_data = request.post_data
    except Exception:
        return ""
    if callable(raw_post_data):
        try:
            raw_post_data = raw_post_data()
        except Exception:
            return ""
    if isinstance(raw_post_data, (bytes, bytearray)):
        return bytes(raw_post_data).decode("utf-8", errors="ignore")
    return str(raw_post_data or "")


def _short_url(url: str, max_len: int = 88) -> str:
    if len(url) <= max_len:
        return url
    return f"{url[: max_len - 3]}..."


def _request_label(request) -> str:
    try:
        method = str(request.method or "").upper()
    except Exception:
        method = "?"
    try:
        raw_url = str(request.url or "")
    except Exception:
        raw_url = ""
    if not raw_url:
        return method
    parsed = urlparse(raw_url)
    host = parsed.hostname or ""
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?..."
    return f"{method} {host}{path}"


def _token_rule_label(rule: TokenCaptureRule) -> str:
    bits = [f"{rule.source}:{rule.key}"]
    if rule.method:
        bits.append(rule.method.upper())
    if rule.host:
        bits.append(rule.host)
    if rule.path_regex:
        bits.append(f"path~{rule.path_regex}")
    return " ".join(bits)


def _request_route_info(request) -> tuple[str, str, str] | None:
    try:
        parsed = urlparse(str(request.url))
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
        method = str(request.method or "").upper()
    except Exception:
        return None
    return host, path, method


def _request_matches_any_rule(request, rules: list[TokenCaptureRule]) -> bool:
    route = _request_route_info(request)
    if route is None:
        return False
    host, path, method = route
    for rule in rules:
        if _rule_matches_request(rule, host=host, path=path, method=method):
            return True
    return False


def _rule_matches_request(rule: TokenCaptureRule, *, host: str, path: str, method: str) -> bool:
    if rule.host:
        normalized = rule.host.lower()
        if host != normalized and not host.endswith(f".{normalized}"):
            return False

    if rule.method and method != rule.method.upper():
        return False

    if rule.path_regex:
        try:
            if re.search(rule.path_regex, path) is None:
                return False
        except re.error:
            return False

    return True


def _extract_token_from_request(
    request,
    rules: list[TokenCaptureRule],
) -> tuple[str, str] | None:
    if not rules:
        return None

    route = _request_route_info(request)
    if route is None:
        return None
    host, path, method = route

    headers: dict[str, str] | None = None
    post_data: str | None = None

    for rule in rules:
        if not _rule_matches_request(rule, host=host, path=path, method=method):
            continue

        value: str | None = None
        source = rule.source.lower()
        if source == "request.header":
            if headers is None:
                headers = _request_headers_safe(request)
            value = _header_value(headers, rule.key)
        elif source == "request.form":
            if post_data is None:
                post_data = _request_post_data_safe(request)
            value = _form_value(post_data, rule.key)

        if value is None:
            continue
        if rule.strip_prefix and value.startswith(rule.strip_prefix):
            value = value[len(rule.strip_prefix) :]
        if value:
            source = f"{_token_rule_label(rule)} <= {_request_label(request)}"
            return value, source

    return None


async def _capture_auth_once(
    playwright_async_api,
    domain: str,
    required_cookies: list[str],
    token_rules: list[TokenCaptureRule],
    poll_seconds: float = 1.0,
    debug_cb: Callable[[str], None] | None = None,
) -> tuple[dict[str, str], str | None]:
    required = [c for c in required_cookies if c]
    if not required and not token_rules:
        raise BrowserLoginError(
            "No required cookie keys or token capture rules configured for browser login"
        )

    async with playwright_async_api.async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        captured_token: str | None = None
        captured_token_source: str | None = None
        token_candidate_count = 0
        last_token_candidate: str | None = None
        last_debug_state: tuple | None = None

        if debug_cb:
            if required:
                _emit_debug(debug_cb, f"required cookies: {', '.join(required)}")
            else:
                _emit_debug(debug_cb, "required cookies: none")
            if token_rules:
                for idx, rule in enumerate(token_rules, start=1):
                    _emit_debug(debug_cb, f"token rule[{idx}]: {_token_rule_label(rule)}")
            else:
                _emit_debug(debug_cb, "token capture: none")

        def _handle_request(request) -> None:
            nonlocal captured_token
            nonlocal captured_token_source
            nonlocal token_candidate_count
            nonlocal last_token_candidate
            if captured_token is not None:
                return
            try:
                if _request_matches_any_rule(request, token_rules):
                    token_candidate_count += 1
                    last_token_candidate = _request_label(request)
                token_match = _extract_token_from_request(request, token_rules)
                if token_match:
                    captured_token, captured_token_source = token_match
                    if debug_cb:
                        _emit_debug(debug_cb, f"captured token via {captured_token_source}")
            except Exception:
                # Never let Playwright request events crash the login flow.
                return

        context.on("request", _handle_request)
        page = await context.new_page()
        await page.goto(f"https://{domain}", wait_until="domcontentloaded")

        while True:
            cookies = await context.cookies()
            by_name = {
                str(c.get("name", "")): str(c.get("value", ""))
                for c in cookies
                if c.get("name")
            }
            have_cookies = [name for name in required if name in by_name]
            missing_cookies = [name for name in required if name not in by_name]

            tab_urls: list[str] = []
            for pg in list(context.pages):
                try:
                    tab_urls.append(_short_url(str(pg.url or "")))
                except Exception:
                    tab_urls.append("<unknown>")

            if debug_cb:
                debug_state = (
                    tuple(have_cookies),
                    tuple(missing_cookies),
                    bool(captured_token),
                    captured_token_source or "",
                    token_candidate_count,
                    last_token_candidate or "",
                    tuple(tab_urls),
                )
                if debug_state != last_debug_state:
                    cookies_summary = (
                        f"cookies {len(have_cookies)}/{len(required)}"
                        if required
                        else "cookies n/a"
                    )
                    if required:
                        have_txt = ",".join(have_cookies) if have_cookies else "-"
                        missing_txt = ",".join(missing_cookies) if missing_cookies else "-"
                        cookies_summary = (
                            f"{cookies_summary} have=[{have_txt}] missing=[{missing_txt}]"
                        )
                    token_summary = (
                        f"token={'present' if captured_token else 'missing'}"
                        + (
                            f" ({captured_token_source})"
                            if captured_token and captured_token_source
                            else ""
                        )
                    )
                    if not captured_token:
                        token_summary = (
                            f"{token_summary} candidates={token_candidate_count}"
                            + (
                                f" last={last_token_candidate}"
                                if last_token_candidate
                                else ""
                            )
                        )
                    tabs_summary = (
                        f"tabs={len(tab_urls)} "
                        + "; ".join(tab_urls if tab_urls else ["<none>"])
                    )
                    _emit_debug(debug_cb, f"{cookies_summary} | {token_summary} | {tabs_summary}")
                    last_debug_state = debug_state

            cookies_ready = all(name in by_name for name in required)
            token_ready = (not token_rules) or (captured_token is not None)
            if cookies_ready and token_ready:
                await browser.close()
                out_cookies = {name: by_name[name] for name in required}
                return out_cookies, captured_token
            await asyncio.sleep(poll_seconds)


def capture_auth_with_browser(
    domain: str,
    required_cookies: list[str],
    token_rules: list[TokenCaptureRule] | None = None,
    status_cb: Callable[[str], None] | None = None,
    debug_cb: Callable[[str], None] | None = None,
) -> tuple[dict[str, str], str | None]:
    """Open browser and wait until required auth values are present."""
    normalized_rules = token_rules or []
    playwright_async_api = _ensure_playwright_package(status_cb)

    try:
        return asyncio.run(
            _capture_auth_once(
                playwright_async_api,
                domain,
                required_cookies,
                normalized_rules,
                debug_cb=debug_cb,
            )
        )
    except KeyboardInterrupt:
        raise BrowserLoginCancelled("Login cancelled by user")
    except Exception as e:
        if _is_missing_browser_error(e):
            _install_chromium(status_cb)
            try:
                return asyncio.run(
                    _capture_auth_once(
                        playwright_async_api,
                        domain,
                        required_cookies,
                        normalized_rules,
                        debug_cb=debug_cb,
                    )
                )
            except KeyboardInterrupt:
                raise BrowserLoginCancelled("Login cancelled by user")
            except Exception as inner:
                raise BrowserLoginError(str(inner))
        raise BrowserLoginError(str(e))


def capture_cookies_with_browser(
    domain: str,
    required_cookies: list[str],
    status_cb: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Backward-compatible wrapper returning only cookies."""
    cookies, _ = capture_auth_with_browser(
        domain=domain,
        required_cookies=required_cookies,
        token_rules=[],
        status_cb=status_cb,
    )
    return cookies
