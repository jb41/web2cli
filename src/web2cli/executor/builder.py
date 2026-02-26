"""Build HTTP Request objects from adapter specs or custom scripts."""

import importlib.util
import json
import re
from pathlib import Path

from web2cli.types import AdapterMeta, CommandSpec, Request, Session


def resolve_template(template: str, args: dict) -> str | None:
    """Resolve {{arg_name}} placeholders in a template string.

    Returns None if the template references an arg whose value is None.
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()
        val = args.get(key)
        if val is None:
            raise _MissingArg()
        return str(val)

    try:
        return re.sub(r"\{\{(\w+)\}\}", _replace, template)
    except _MissingArg:
        return None


class _MissingArg(Exception):
    pass


def build_from_spec(
    cmd: CommandSpec,
    args: dict,
    session: Session | None,
    meta: AdapterMeta,
) -> Request:
    """Build Request from declarative YAML spec."""
    req = cmd.request

    # URL — absolute or relative to base_url
    raw_url = req.get("url", "/")
    url = resolve_template(raw_url, args)
    if url and not url.startswith("http"):
        url = meta.base_url.rstrip("/") + "/" + url.lstrip("/")

    # Query params — resolve templates, omit None values
    params = {}
    for key, tmpl in req.get("params", {}).items():
        val = resolve_template(str(tmpl), args)
        if val is not None:
            params[key] = val

    # Headers — merge default_headers + command headers + auth
    headers = dict(meta.default_headers)
    for key, tmpl in req.get("headers", {}).items():
        val = resolve_template(str(tmpl), args)
        if val is not None:
            headers[key] = val

    # Cookies from session
    cookies = {}
    if session and session.data.get("cookies"):
        cookies = dict(session.data["cookies"])

    # Token auth → Authorization header
    if session and session.data.get("token"):
        headers["Authorization"] = session.data["token"]

    # Body
    body = None
    content_type = None
    body_spec = req.get("body")
    if body_spec:
        content_type = body_spec.get("content_type", "application/json")
        template = body_spec.get("template", {})
        if isinstance(template, dict):
            body = {}
            for key, tmpl in template.items():
                val = resolve_template(str(tmpl), args)
                if val is not None:
                    body[key] = val
        elif isinstance(template, str):
            body = resolve_template(template, args)

    return Request(
        method=req.get("method", "GET"),
        url=url,
        params=params,
        headers=headers,
        cookies=cookies,
        body=body,
        content_type=content_type,
    )


def build_from_script(
    script_path: str,
    adapter_dir: Path,
    args: dict,
    session: Session | None,
) -> Request:
    """Dynamically import and call a custom builder script."""
    full_path = adapter_dir / script_path
    spec = importlib.util.spec_from_file_location("custom_builder", full_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    session_dict = None
    if session:
        session_dict = {
            "auth_type": session.auth_type,
            "cookies": session.data.get("cookies", {}),
            "token": session.data.get("token"),
        }

    return module.build(args, session_dict)
