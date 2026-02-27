"""Command pipeline execution engine."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any, Callable

import jmespath

from web2cli.executor.http import HttpError, execute
from web2cli.parser.custom import parse_custom
from web2cli.types import AdapterSpec, CommandSpec, Request, Session
from web2cli.providers import get_provider
from web2cli.runtime.cache import load_cache, save_cache
from web2cli.runtime.parser import apply_post_ops, parse_records
from web2cli.runtime.template import render_value


@dataclass
class ExecutionResult:
    records: list[dict[str, Any]]
    last_response_body: str | None = None
    trace_lines: list[str] | None = None


def _payload_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="ignore"))
    if isinstance(value, bytes):
        return len(value)
    try:
        return len(json.dumps(value))
    except Exception:
        return len(str(value))


def _summarize(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        keys = ", ".join(list(value.keys())[:5])
        return f"dict[{len(value)}] keys=[{keys}]"
    if value is None:
        return "none"
    return type(value).__name__


def _jmespath_expr(path: str) -> str:
    if path == "$":
        return "@"
    if path.startswith("$."):
        return path[2:]
    if path.startswith("$["):
        return path[1:]
    return path


def _join_url(base_url: str, raw_url: str) -> str:
    if raw_url.startswith("http"):
        return raw_url
    return base_url.rstrip("/") + "/" + raw_url.lstrip("/")


def _omit_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _session_cookies(session: Session | None) -> dict[str, str]:
    if session and session.data.get("cookies"):
        return dict(session.data["cookies"])
    return {}


def _session_token(session: Session | None) -> str | None:
    if session and session.data.get("token"):
        return str(session.data["token"])
    return None


def _method_matches_session(method: dict, session: Session | None) -> bool:
    if session is None:
        return False
    mtype = str(method.get("type", "")).lower()
    if mtype == "token":
        return _session_token(session) is not None
    if mtype == "cookies":
        return bool(_session_cookies(session))
    return False


def _apply_auth_injection(
    request: Request,
    request_spec: dict[str, Any],
    auth_spec: dict | None,
    session: Session | None,
) -> Request:
    """Apply auth injection policy from adapter auth methods."""
    # Default policy: token session -> Authorization header.
    token = _session_token(session)
    if token and "Authorization" not in request.headers:
        request.headers["Authorization"] = token

    if not auth_spec:
        return request

    methods = auth_spec.get("methods", [])
    for method in methods:
        if not _method_matches_session(method, session):
            continue
        inject = method.get("inject") or {}
        if not inject:
            continue

        target = str(inject.get("target", "")).lower()
        key = inject.get("key")
        prefix = inject.get("prefix", "")
        if not key:
            continue

        value: str | None = None
        mtype = str(method.get("type", "")).lower()
        if mtype == "token":
            t = _session_token(session)
            value = f"{prefix}{t}" if t is not None else None
        elif mtype == "cookies":
            cookie_name = inject.get("cookie")
            cookies = _session_cookies(session)
            if cookie_name:
                raw = cookies.get(cookie_name)
                value = f"{prefix}{raw}" if raw is not None else None

        if value is None:
            continue

        if target == "header":
            request.headers[str(key)] = value
        elif target == "query":
            request.params[str(key)] = value
        elif target == "cookie":
            request.cookies[str(key)] = value
        elif target == "form":
            if isinstance(request.body, dict):
                request.body[str(key)] = value
                if not request.content_type:
                    request.content_type = "application/x-www-form-urlencoded"

    return request


def _build_request(
    adapter: AdapterSpec,
    request_spec: dict[str, Any],
    ctx: dict[str, Any],
    session: Session | None,
) -> Request:
    if request_spec.get("provider"):
        provider_name = request_spec["provider"]
        provider = get_provider(provider_name)
        req = provider.build_request(request_spec, ctx, adapter, session)
        return _apply_auth_injection(req, request_spec, adapter.auth, session)

    method = str(request_spec.get("method", "GET")).upper()
    url = _join_url(adapter.meta.base_url, str(render_value(request_spec.get("url", "/"), ctx)))

    params = render_value(request_spec.get("params", {}), ctx) or {}
    headers = dict(adapter.meta.default_headers)
    headers.update(render_value(request_spec.get("headers", {}), ctx) or {})
    cookies = _session_cookies(session)
    cookies.update(render_value(request_spec.get("cookies", {}), ctx) or {})

    body = None
    content_type = None
    body_spec = request_spec.get("body")
    if body_spec:
        if isinstance(body_spec, dict):
            encoding = str(body_spec.get("encoding", "json")).lower()
            template = render_value(body_spec.get("template", {}), ctx)
            if encoding == "json":
                body = template
                content_type = "application/json"
            elif encoding == "form":
                body = template
                content_type = "application/x-www-form-urlencoded"
            elif encoding == "text":
                body = template if isinstance(template, str) else json.dumps(template)
                content_type = "text/plain"
            elif encoding == "bytes":
                body = template
                content_type = body_spec.get("content_type", "application/octet-stream")
            else:
                raise ValueError(f"Unsupported body encoding: {encoding}")
        else:
            body = render_value(body_spec, ctx)

    request = Request(
        method=method,
        url=url,
        params=_omit_none(params),
        headers=_omit_none(headers),
        cookies=_omit_none(cookies),
        body=body,
        content_type=content_type,
    )
    if content_type and "Content-Type" not in request.headers and "content-type" not in request.headers:
        request.headers["Content-Type"] = content_type
    return _apply_auth_injection(request, request_spec, adapter.auth, session)


def _execute_request(
    request: Request,
    adapter: AdapterSpec,
    verbose: bool = False,
    trace: Callable[[str], None] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    prefix = f"{label}: " if label else ""
    if trace:
        trace(
            f"{prefix}request {request.method} {request.url} "
            f"params={len(request.params)} headers={len(request.headers)} "
            f"cookies={len(request.cookies)} body_bytes={_payload_size(request.body)}"
        )

    status, headers, body = asyncio.run(
        execute(request, verbose=verbose, impersonate=adapter.meta.impersonate)
    )
    parsed_json = None
    if isinstance(body, str):
        try:
            parsed_json = json.loads(body)
        except json.JSONDecodeError:
            parsed_json = None

    result = {
        "status": status,
        "headers": headers,
        "body": body,
        "json": parsed_json,
        "request": request,
    }
    if trace:
        trace(
            f"{prefix}response status={status} body_bytes={_payload_size(body)} "
            f"json={'yes' if parsed_json is not None else 'no'}"
        )
    return result


def _set_cursor(
    request_spec: dict[str, Any],
    cursor_param: str,
    cursor_location: str,
    cursor_value: str,
) -> dict[str, Any]:
    spec = copy.deepcopy(request_spec)
    location = cursor_location.lower()
    if location == "params":
        spec.setdefault("params", {})
        spec["params"][cursor_param] = cursor_value
        return spec

    # body/form cursor
    spec.setdefault("body", {})
    body = spec["body"]
    if isinstance(body, dict) and "template" in body:
        body.setdefault("template", {})
        if isinstance(body["template"], dict):
            body["template"][cursor_param] = cursor_value
    elif isinstance(body, dict):
        body[cursor_param] = cursor_value
    return spec


def _fetch_resource_records(
    adapter: AdapterSpec,
    resource_name: str,
    resource_spec: dict[str, Any],
    ctx: dict[str, Any],
    session: Session | None,
    verbose: bool = False,
    trace: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    cache_spec = resource_spec.get("cache", {})
    cache_key_tmpl = cache_spec.get("key", resource_name)
    cache_key = str(render_value(cache_key_tmpl, ctx))
    ttl = cache_spec.get("ttl")
    ttl_int = int(ttl) if isinstance(ttl, (int, str)) and str(ttl).isdigit() else None

    cached = load_cache(adapter.meta.domain, cache_key, ttl=ttl_int)
    if isinstance(cached, list):
        if trace:
            trace(
                f"resolve resource={resource_name} cache=hit key={cache_key} "
                f"records={len(cached)}"
            )
        return cached
    if trace:
        trace(f"resolve resource={resource_name} cache=miss key={cache_key}")

    request_spec = resource_spec.get("request", {})
    response_spec = resource_spec.get("response", resource_spec.get("parse", {"format": "json"}))

    paginate = resource_spec.get("paginate", {})
    cursor_param = paginate.get("cursor_param")
    cursor_path = paginate.get("cursor_path")
    cursor_location = paginate.get("cursor_location", "params")
    cursor = None
    seen_cursors: set[str] = set()

    records: list[dict[str, Any]] = []
    page = 0
    while True:
        page += 1
        current_spec = request_spec
        if cursor and cursor_param:
            current_spec = _set_cursor(current_spec, str(cursor_param), str(cursor_location), str(cursor))

        req = _build_request(adapter, current_spec, ctx, session)
        result = _execute_request(
            req,
            adapter,
            verbose=verbose,
            trace=trace,
            label=f"resource:{resource_name}:page:{page}",
        )
        page_records = parse_records(result, response_spec, ctx)
        records.extend(page_records)
        if trace:
            trace(
                f"resource={resource_name} page={page} parsed_records={len(page_records)} "
                f"total_records={len(records)}"
            )

        if not cursor_path:
            break

        parsed_json = result.get("json")
        if parsed_json is None:
            break
        next_cursor = jmespath.search(_jmespath_expr(str(cursor_path)), parsed_json)
        if not next_cursor:
            break
        next_cursor = str(next_cursor)
        if next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    save_cache(adapter.meta.domain, cache_key, records)
    if trace:
        trace(
            f"resolve resource={resource_name} cache=write key={cache_key} "
            f"records={len(records)}"
        )
    return records


def _run_resolve_step(
    step_spec: dict[str, Any],
    adapter: AdapterSpec,
    ctx: dict[str, Any],
    session: Session | None,
    verbose: bool = False,
    trace: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    resource_name = step_spec["resource"]
    resource_spec = adapter.resources.get(resource_name)
    if resource_spec is None:
        raise ValueError(f"Unknown resource '{resource_name}'")

    records = _fetch_resource_records(
        adapter,
        resource_name,
        resource_spec,
        ctx,
        session,
        verbose=verbose,
        trace=trace,
    )

    input_value = render_value(step_spec.get("input"), ctx)
    by = step_spec.get("by", "name")
    out = step_spec.get("value", "id")
    mode = str(step_spec.get("match", "ci_equals")).lower()

    map_by_by = {
        str(r.get(by)): r.get(out)
        for r in records
        if r.get(by) is not None and r.get(out) is not None
    }
    map_by_out = {
        str(r.get(out)): r.get(by)
        for r in records
        if r.get(by) is not None and r.get(out) is not None
    }
    records_by_out = {
        str(r.get(out)): r
        for r in records
        if r.get(out) is not None
    }

    if input_value is None:
        if trace:
            trace(
                f"resolve resource={resource_name} input=<none> "
                f"records={len(records)}"
            )
        return {
            "input": None,
            "record": None,
            out: None,
            "records": records,
            "by": by,
            "value": out,
            f"map_by_{by}": map_by_by,
            f"map_by_{out}": map_by_out,
            f"records_by_{out}": records_by_out,
        }

    matched = None
    for rec in records:
        rv = rec.get(by)
        if rv is None:
            continue
        if mode == "equals" and str(rv) == str(input_value):
            matched = rec
            break
        if mode == "ci_equals" and str(rv).lower() == str(input_value).lower():
            matched = rec
            break
        if mode == "contains" and str(input_value).lower() in str(rv).lower():
            matched = rec
            break

    if matched is None:
        preview = ", ".join(str(r.get(by, "")) for r in records[:30] if r.get(by))
        raise ValueError(
            f"Could not resolve '{input_value}' via resource '{resource_name}'. "
            f"Available: {preview}"
        )

    result = {
        "input": input_value,
        "record": matched,
        out: matched.get(out),
        "records": records,
        "by": by,
        "value": out,
        f"map_by_{by}": map_by_by,
        f"map_by_{out}": map_by_out,
        f"records_by_{out}": records_by_out,
    }
    # Also expose common alias used by templates.
    if out != "id":
        result["id"] = matched.get(out)
    if trace:
        trace(
            f"resolve resource={resource_name} input={input_value!r} "
            f"matched_{out}={matched.get(out)!r}"
        )
    return result


def _run_request_step(
    step_spec: dict[str, Any],
    adapter: AdapterSpec,
    ctx: dict[str, Any],
    session: Session | None,
    verbose: bool = False,
    trace: Callable[[str], None] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    req = _build_request(adapter, step_spec, ctx, session)
    result = _execute_request(
        req,
        adapter,
        verbose=verbose,
        trace=trace,
        label=label,
    )

    # Useful for providers with rotating request internals (e.g. X query ids).
    if step_spec.get("provider") and result.get("status", 0) >= 400:
        retry_ctx = copy.deepcopy(ctx)
        retry_ctx.setdefault("args", {})
        retry_ctx["args"]["_retry"] = True
        req2 = _build_request(adapter, step_spec, retry_ctx, session)
        if trace:
            trace(f"{label or 'request'} retry with args._retry=true")
        result2 = _execute_request(
            req2,
            adapter,
            verbose=verbose,
            trace=trace,
            label=label,
        )
        if result2.get("status", 0) < result.get("status", 0):
            result = result2

    return result


def _run_fanout_step(
    step_spec: dict[str, Any],
    adapter: AdapterSpec,
    ctx: dict[str, Any],
    session: Session | None,
    verbose: bool = False,
    trace: Callable[[str], None] | None = None,
    label: str | None = None,
) -> list[dict[str, Any]]:
    items = render_value(step_spec.get("items_from"), ctx)
    if items is None:
        if trace:
            trace(f"{label or 'fanout'} items=0 (items_from resolved to null)")
        return []
    if not isinstance(items, list):
        items = [items]

    limit = render_value(step_spec.get("limit"), ctx)
    try:
        if limit is not None:
            items = items[: int(limit)]
    except (TypeError, ValueError):
        pass

    if trace:
        trace(f"{label or 'fanout'} items={len(items)}")

    req_spec = step_spec.get("request", {})
    responses: list[dict[str, Any]] = []
    statuses: dict[int, int] = {}
    for idx, item in enumerate(items):
        iter_ctx = copy.deepcopy(ctx)
        iter_ctx["item"] = item
        iter_ctx["index"] = idx
        req = _build_request(adapter, req_spec, iter_ctx, session)
        result = _execute_request(
            req,
            adapter,
            verbose=verbose,
            trace=trace,
            label=f"{label or 'fanout'}[{idx}]",
        )
        result["item"] = item
        result["index"] = idx + 1
        status = int(result.get("status", 0) or 0)
        statuses[status] = statuses.get(status, 0) + 1
        responses.append(result)

    if trace:
        status_summary = ", ".join(f"{k}x{v}" for k, v in sorted(statuses.items()))
        trace(
            f"{label or 'fanout'} responses={len(responses)} "
            f"statuses=[{status_summary}]"
        )
    return responses


def _records_from_output(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, list):
        return [r for r in output if isinstance(r, dict)]
    if isinstance(output, dict):
        records = output.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


def execute_command(
    adapter: AdapterSpec,
    cmd: CommandSpec,
    args: dict[str, Any],
    session: Session | None,
    verbose: bool = False,
    trace: bool = False,
) -> ExecutionResult:
    """Execute a command pipeline."""
    trace_lines: list[str] = []

    def _trace(msg: str) -> None:
        if trace:
            trace_lines.append(msg)

    ctx: dict[str, Any] = {
        "args": dict(args),
        "auth": session.data if session else {},
        "steps": {},
    }

    pipeline = list(cmd.pipeline or [])
    if not pipeline:
        return ExecutionResult(records=[], trace_lines=(trace_lines if trace else None))

    last_output: Any = None
    last_body: str | None = None

    _trace(
        f"command={adapter.meta.name}.{cmd.name} steps={len(pipeline)} "
        f"args={sorted(ctx.get('args', {}).keys())}"
    )

    for idx, raw_step in enumerate(pipeline):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Invalid pipeline step at index {idx}: {raw_step!r}")

        if "resolve" in raw_step:
            step_spec = raw_step["resolve"] or {}
            step_name = step_spec.get("name") or raw_step.get("name") or f"resolve_{idx}"
            _trace(f"step[{idx}] resolve:{step_name} start")
            output = _run_resolve_step(
                step_spec, adapter, ctx, session, verbose=verbose, trace=_trace
            )
            ctx["steps"][step_name] = output
            last_output = output
            _trace(f"step[{idx}] resolve:{step_name} done output={_summarize(output)}")
            continue

        if "request" in raw_step:
            step_spec = raw_step["request"] or {}
            step_name = step_spec.get("name") or raw_step.get("name") or f"request_{idx}"
            _trace(f"step[{idx}] request:{step_name} start")
            output = _run_request_step(
                step_spec,
                adapter,
                ctx,
                session,
                verbose=verbose,
                trace=_trace,
                label=f"step[{idx}] request:{step_name}",
            )
            ctx["steps"][step_name] = output
            last_output = output
            last_body = output.get("body")
            _trace(
                f"step[{idx}] request:{step_name} done "
                f"status={output.get('status')} output={_summarize(output)}"
            )
            continue

        if "fanout" in raw_step:
            step_spec = raw_step["fanout"] or {}
            step_name = step_spec.get("name") or raw_step.get("name") or f"fanout_{idx}"
            _trace(f"step[{idx}] fanout:{step_name} start")
            output = _run_fanout_step(
                step_spec,
                adapter,
                ctx,
                session,
                verbose=verbose,
                trace=_trace,
                label=f"step[{idx}] fanout:{step_name}",
            )
            ctx["steps"][step_name] = output
            last_output = output
            if output:
                last_body = output[-1].get("body")
            _trace(f"step[{idx}] fanout:{step_name} done output={_summarize(output)}")
            continue

        if "parse" in raw_step:
            step_spec = raw_step["parse"] or {}
            step_name = step_spec.get("name") or raw_step.get("name") or f"parse_{idx}"
            from_step = step_spec.get("from")
            source = ctx["steps"].get(from_step) if from_step else last_output
            _trace(
                f"step[{idx}] parse:{step_name} start from="
                f"{from_step or '<last>'}"
            )
            if from_step and source is None:
                _trace(f"step[{idx}] parse:{step_name} warning missing source step='{from_step}'")

            if step_spec.get("parser") == "custom":
                if source is None:
                    output = []
                elif isinstance(source, dict):
                    output = parse_custom(
                        step_spec["script"],
                        adapter.adapter_dir,
                        source.get("status", 0),
                        source.get("headers", {}),
                        source.get("body", ""),
                        ctx["args"],
                    )
                else:
                    output = []
            else:
                output = parse_records(source, step_spec, ctx)

            ctx["steps"][step_name] = output
            last_output = output
            _trace(f"step[{idx}] parse:{step_name} done output={_summarize(output)}")
            continue

        if "transform" in raw_step:
            step_spec = raw_step["transform"] or {}
            step_name = step_spec.get("name") or raw_step.get("name") or f"transform_{idx}"
            from_step = step_spec.get("from")
            source = ctx["steps"].get(from_step) if from_step else last_output
            _trace(
                f"step[{idx}] transform:{step_name} start from="
                f"{from_step or '<last>'}"
            )
            if from_step and source is None:
                _trace(
                    f"step[{idx}] transform:{step_name} warning missing source "
                    f"step='{from_step}'"
                )
            records = _records_from_output(source)
            output = apply_post_ops(records, step_spec.get("ops"), ctx)
            ctx["steps"][step_name] = output
            last_output = output
            _trace(
                f"step[{idx}] transform:{step_name} done output={_summarize(output)}"
            )
            continue

        raise ValueError(f"Unsupported pipeline step keys: {list(raw_step.keys())}")

    output_from = cmd.output.get("from_step")
    if output_from and output_from in ctx["steps"]:
        records = _records_from_output(ctx["steps"][output_from])
    else:
        records = _records_from_output(last_output)

    _trace(
        f"result records={len(records)} output_from={output_from or '<last>'} "
        f"last_response_body_bytes={_payload_size(last_body)}"
    )
    return ExecutionResult(
        records=records,
        last_response_body=last_body,
        trace_lines=(trace_lines if trace else None),
    )
