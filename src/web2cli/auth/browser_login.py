"""Browser-assisted auth capture for login command."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen
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


@dataclass(frozen=True)
class AutoCdpSession:
    """Process/session details for auto-started local Chrome over CDP."""

    cdp_url: str
    process: subprocess.Popen[str]
    user_data_dir: Path
    port: int


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
        or "chromium distribution 'chrome'" in text
        or "cannot find chromium" in text
        or "download new browsers" in text
        or ("playwright install" in text and "chromium" in text)
    )


def _install_chromium(status_cb: Callable[[str], None] | None) -> None:
    _emit(status_cb, "Installing browser engine (one-time, ~250MB)...")
    _run_command([sys.executable, "-m", "playwright", "install", "chromium"])


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _find_chrome_executable() -> str | None:
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

    if sys.platform.startswith("win"):
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

    for cmd in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _wait_for_cdp_ready(port: int, timeout_seconds: float = 12.0) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with urlopen(url, timeout=1.0) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(payload or "{}")
                if isinstance(data, dict) and data.get("webSocketDebuggerUrl"):
                    return True
        except Exception:
            pass

        now = time.monotonic()
        if now >= deadline:
            return False
        time.sleep(0.2)


def _stop_auto_cdp_session(session: AutoCdpSession) -> None:
    proc = session.process
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
    except Exception:
        pass
    shutil.rmtree(session.user_data_dir, ignore_errors=True)


def find_local_chrome_executable() -> str | None:
    """Return local Chrome/Chromium executable path if found."""
    return _find_chrome_executable()


def probe_cdp_endpoint(cdp_url: str, timeout_seconds: float = 2.0) -> bool:
    """Best-effort probe for a running CDP endpoint."""
    url = cdp_url.rstrip("/") + "/json/version"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(payload or "{}")
                if isinstance(data, dict) and data.get("webSocketDebuggerUrl"):
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def start_auto_cdp_chrome(
    *,
    status_cb: Callable[[str], None] | None = None,
    debug_cb: Callable[[str], None] | None = None,
    chrome_path: str | None = None,
    port: int | None = None,
    headless: bool = False,
) -> AutoCdpSession:
    """Start local Chrome with CDP and return session metadata."""
    return _start_auto_cdp_chrome(
        status_cb=status_cb,
        debug_cb=debug_cb,
        chrome_path=chrome_path,
        port=port,
        headless=headless,
    )


def stop_auto_cdp_chrome(session: AutoCdpSession) -> None:
    """Stop auto-started CDP Chrome session and remove temp profile."""
    _stop_auto_cdp_session(session)


def _start_auto_cdp_chrome(
    *,
    status_cb: Callable[[str], None] | None,
    debug_cb: Callable[[str], None] | None,
    chrome_path: str | None = None,
    port: int | None = None,
    headless: bool = False,
) -> AutoCdpSession:
    binary = chrome_path or _find_chrome_executable()
    if not binary:
        raise BrowserLoginError(
            "Could not find local Chrome executable for --browser-cdp-auto. "
            "Use --browser-cdp-url or --browser-chrome-path."
        )

    cdp_port = int(port or _pick_free_port())
    user_data_dir = Path(tempfile.mkdtemp(prefix="web2cli-cdp-"))
    args = [
        binary,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={str(user_data_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")

    _emit(status_cb, "Starting local browser...")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if debug_cb:
        _emit_debug(debug_cb, f"cdp auto: chrome={binary}")
        _emit_debug(debug_cb, f"cdp auto: port={cdp_port} profile={user_data_dir}")

    ready = _wait_for_cdp_ready(cdp_port, timeout_seconds=12.0)
    if not ready:
        _stop_auto_cdp_session(
            AutoCdpSession(
                cdp_url=f"http://127.0.0.1:{cdp_port}",
                process=proc,
                user_data_dir=user_data_dir,
                port=cdp_port,
            )
        )
        raise BrowserLoginError(
            "Failed to start local Chrome CDP endpoint. "
            "Try --browser-cdp-url with an existing Chrome instance."
        )

    return AutoCdpSession(
        cdp_url=f"http://127.0.0.1:{cdp_port}",
        process=proc,
        user_data_dir=user_data_dir,
        port=cdp_port,
    )


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


async def _apply_stealth_init_script(context) -> None:
    # Best-effort JS patches to reduce obvious automation fingerprints.
    script = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""
    try:
        await context.add_init_script(script)
    except Exception:
        return


async def _launch_browser_with_fallback(
    playwright_async_api,
    debug_cb: Callable[[str], None] | None,
):
    common_args = [
        "--disable-features=PrivateNetworkAccessRespectPreflightResults,"
        "BlockInsecurePrivateNetworkRequests",
        "--disable-blink-features=AutomationControlled",
    ]

    # Prefer user-installed Chrome first (looks less synthetic than Playwright Chromium).
    launch_profiles = [
        (
            "chrome",
            {
                "channel": "chrome",
                "headless": False,
                "args": common_args,
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            },
        ),
        (
            "chromium",
            {
                "headless": False,
                "args": common_args,
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            },
        ),
    ]

    errors: list[str] = []
    for profile_name, options in launch_profiles:
        try:
            browser = await playwright_async_api.chromium.launch(**options)
            if debug_cb:
                _emit_debug(debug_cb, f"browser profile: {profile_name}")
            return browser, profile_name
        except Exception as e:
            errors.append(f"{profile_name}: {e}")
            if debug_cb:
                _emit_debug(debug_cb, f"browser profile failed: {profile_name}: {e}")

    detail = " | ".join(errors)
    raise BrowserLoginError(f"Failed to launch browser ({detail})")


async def _open_browser_and_context(
    playwright_async_api,
    *,
    debug_cb: Callable[[str], None] | None,
    cdp_url: str | None,
):
    if cdp_url:
        browser = await playwright_async_api.chromium.connect_over_cdp(cdp_url)
        contexts = list(browser.contexts)
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context(viewport={"width": 1280, "height": 900})
        if debug_cb:
            _emit_debug(debug_cb, f"browser profile: cdp ({cdp_url})")
            _emit_debug(
                debug_cb,
                f"cdp contexts={len(contexts)} tabs={len(getattr(context, 'pages', []))}",
            )
        return browser, context, "cdp", False

    browser, browser_profile = await _launch_browser_with_fallback(
        playwright_async_api,
        debug_cb=debug_cb,
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
    )
    return browser, context, browser_profile, True


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
    cdp_url: str | None = None,
) -> tuple[dict[str, str], str | None]:
    required = [c for c in required_cookies if c]
    if not required and not token_rules:
        raise BrowserLoginError(
            "No required cookie keys or token capture rules configured for browser login"
        )

    async with playwright_async_api.async_playwright() as p:
        browser, context, browser_profile, managed_browser = await _open_browser_and_context(
            p,
            debug_cb=debug_cb,
            cdp_url=cdp_url,
        )
        await _apply_stealth_init_script(context)
        if debug_cb:
            _emit_debug(debug_cb, f"context ready ({browser_profile}, viewport=1280x900)")

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
                if managed_browser:
                    await browser.close()
                else:
                    try:
                        await page.close()
                    except Exception:
                        pass
                out_cookies = {name: by_name[name] for name in required}
                return out_cookies, captured_token
            await asyncio.sleep(poll_seconds)


def capture_auth_with_browser(
    domain: str,
    required_cookies: list[str],
    token_rules: list[TokenCaptureRule] | None = None,
    status_cb: Callable[[str], None] | None = None,
    debug_cb: Callable[[str], None] | None = None,
    cdp_url: str | None = None,
    cdp_auto: bool = False,
    cdp_port: int | None = None,
    chrome_path: str | None = None,
) -> tuple[dict[str, str], str | None]:
    """Open browser and wait until required auth values are present."""
    normalized_rules = token_rules or []
    playwright_async_api = _ensure_playwright_package(status_cb)
    auto_session: AutoCdpSession | None = None

    try:
        # Default behavior: transparently prefer local Chrome via CDP when URL isn't explicit.
        prefer_auto_cdp = cdp_auto or (cdp_url is None)
        if prefer_auto_cdp and cdp_url is None:
            try:
                auto_session = _start_auto_cdp_chrome(
                    status_cb=status_cb,
                    debug_cb=debug_cb,
                    chrome_path=chrome_path,
                    port=cdp_port,
                )
                cdp_url = auto_session.cdp_url
                if debug_cb:
                    _emit_debug(debug_cb, f"cdp auto ready: {cdp_url}")
            except BrowserLoginError as e:
                if cdp_auto:
                    raise
                # Silent fallback for default --browser mode.
                _emit(status_cb, "Local browser unavailable, falling back to embedded browser...")
                if debug_cb:
                    _emit_debug(debug_cb, f"cdp auto unavailable, fallback to playwright: {e}")
                cdp_url = None

        return asyncio.run(
            _capture_auth_once(
                playwright_async_api,
                domain,
                required_cookies,
                normalized_rules,
                debug_cb=debug_cb,
                cdp_url=cdp_url,
            )
        )
    except KeyboardInterrupt:
        raise BrowserLoginCancelled("Login cancelled by user")
    except Exception as e:
        if _is_missing_browser_error(e):
            try:
                _install_chromium(status_cb)
            except Exception as install_error:
                raise BrowserLoginError(
                    "Browser engine is missing and automatic install failed.\n"
                    "Try manual setup:\n"
                    f"  {sys.executable} -m playwright install chromium\n"
                    "Then verify with:\n"
                    "  web2cli doctor browser --deep\n"
                    f"Install error: {install_error}"
                )
            try:
                return asyncio.run(
                    _capture_auth_once(
                        playwright_async_api,
                        domain,
                        required_cookies,
                        normalized_rules,
                        debug_cb=debug_cb,
                        cdp_url=cdp_url,
                    )
                )
            except KeyboardInterrupt:
                raise BrowserLoginCancelled("Login cancelled by user")
            except Exception as inner:
                raise BrowserLoginError(str(inner))
        raise BrowserLoginError(str(e))
    finally:
        if auto_session is not None:
            _stop_auto_cdp_session(auto_session)


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
