"""Parser helpers for declarative pipeline steps."""

from __future__ import annotations

import json
import re
from typing import Any

import jmespath

from web2cli.parser.html_parser import parse_html
from web2cli.parser.transforms import apply_transform
from web2cli.runtime.template import render_string, resolve_expr


def _jmespath_expr(path: str) -> str:
    """Convert common JSONPath-like syntax to jmespath."""
    if path == "$":
        return "@"
    if path.startswith("$."):
        return path[2:]
    if path.startswith("$["):
        return path[1:]
    return path


def _eval_json_expr(data: Any, expr: str) -> Any:
    if expr is None:
        return None
    return jmespath.search(_jmespath_expr(expr), data)


def _request_to_json(data: Any) -> Any:
    """Normalize request step output or raw value to parsed JSON."""
    if isinstance(data, dict) and "json" in data:
        return data.get("json")
    if isinstance(data, dict) and "body" in data:
        body = data.get("body", "")
        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
        return body
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return data


def _extract_items(parsed: Any, extract: str | None) -> list[Any]:
    if extract:
        items = _eval_json_expr(parsed, extract)
    else:
        items = parsed

    if items is None:
        return []
    if isinstance(items, list):
        return items
    return [items]


def _resolve_field_source(field_spec: dict, item: Any, ctx: dict[str, Any]) -> Any:
    source = field_spec.get("from", field_spec.get("path"))
    if source is None:
        return None

    if isinstance(source, dict):
        coalesce = source.get("coalesce")
        if isinstance(coalesce, list):
            for expr in coalesce:
                value = _eval_json_expr(item, expr) if isinstance(expr, str) else expr
                if value not in (None, "", []):
                    return value
            return None
        value_expr = source.get("value")
        if isinstance(value_expr, str):
            return _eval_json_expr(item, value_expr)
        return value_expr

    if isinstance(source, str):
        # Context expression support, e.g. "steps.users.by_id"
        if source.startswith("ctx."):
            return resolve_expr(source[4:], ctx)
        return _eval_json_expr(item, source)

    return source


def _disable_truncate(ctx: dict[str, Any]) -> bool:
    flags = ctx.get("flags")
    if not isinstance(flags, dict):
        return False
    return bool(flags.get("no_truncate"))


def _apply_ops(value: Any, field_spec: dict, item: Any, ctx: dict[str, Any]) -> Any:
    ops: list[Any] = []
    transform = field_spec.get("transform")
    if transform:
        ops.append(transform)
    if field_spec.get("ops"):
        ops.extend(field_spec["ops"])

    for op in ops:
        if isinstance(op, str):
            value = apply_transform(value, op, disable_truncate=_disable_truncate(ctx))
            continue

        if not isinstance(op, dict) or len(op) != 1:
            continue

        op_name, cfg = next(iter(op.items()))
        if op_name == "map_lookup":
            cfg = cfg or {}
            mapping = resolve_expr(cfg.get("from", ""), ctx) if cfg.get("from") else {}
            if isinstance(mapping, dict):
                key = value
                if key not in mapping and isinstance(key, str):
                    key = key.strip()
                value = mapping.get(key, cfg.get("default", value))
            continue

        if op_name == "join":
            cfg = cfg or {}
            sep = cfg.get("sep", ", ")
            if isinstance(value, list):
                value = sep.join(str(v) for v in value if v is not None)
            continue

        if op_name == "add":
            cfg = cfg or {}
            delta = cfg.get("value", 0)
            try:
                value = (0 if value is None else float(value)) + float(delta)
                if float(value).is_integer():
                    value = int(value)
            except (ValueError, TypeError):
                pass
            continue

        if op_name == "regex_replace":
            cfg = cfg or {}
            pattern = cfg.get("pattern")
            repl = cfg.get("repl", "")
            if pattern is not None and value is not None:
                value = re.sub(pattern, repl, str(value))
            continue

        if op_name == "append_urls":
            cfg = cfg or {}
            path = cfg.get("path")
            sep = cfg.get("sep", " ")
            if path:
                urls = _eval_json_expr(item, path)
                if urls:
                    if not isinstance(urls, list):
                        urls = [urls]
                    urls = [str(u) for u in urls if u]
                    if urls:
                        base = str(value or "").strip()
                        suffix = sep.join(urls)
                        value = f"{base} {suffix}".strip() if base else suffix
            continue

        if op_name == "template":
            cfg = cfg or {}
            template = str(cfg.get("value", "{{value}}"))
            local_ctx = dict(ctx)
            local_ctx["value"] = value
            local_ctx["item"] = item
            value = render_string(template, local_ctx)
            continue

    if value is None and "default" in field_spec:
        return field_spec.get("default")
    return value


def apply_post_ops(
    records: list[dict[str, Any]],
    ops: list[Any] | None,
    ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply record-level operations."""
    if not ops:
        return records

    out = list(records)
    for op in ops:
        if op == "reverse":
            out.reverse()
            continue

        if isinstance(op, dict) and "sort" in op:
            cfg = op.get("sort") or {}
            field = cfg.get("by")
            order = cfg.get("order", "asc")
            if field:
                out.sort(
                    key=lambda r: r.get(field, 0) or 0,
                    reverse=(str(order).lower() == "desc"),
                )
            continue

        if isinstance(op, dict) and "limit" in op:
            n = op.get("limit")
            try:
                n_int = int(n)
                if n_int >= 0:
                    out = out[:n_int]
            except (ValueError, TypeError):
                pass
            continue

        if isinstance(op, dict) and "filter_not_empty" in op:
            field = op.get("filter_not_empty")
            if field:
                out = [r for r in out if r.get(field) not in (None, "", [])]
            continue

        if isinstance(op, dict) and "concat" in op:
            cfg = op.get("concat") or {}
            step_names = cfg.get("steps", [])
            if isinstance(step_names, str):
                step_names = [step_names]

            extra: list[dict[str, Any]] = []
            if ctx and isinstance(step_names, list):
                steps_ctx = ctx.get("steps", {})
                for step_name in step_names:
                    if not step_name:
                        continue
                    extra.extend(_records_from_source(steps_ctx.get(str(step_name))))

            if str(cfg.get("position", "after")).lower() == "before":
                out = extra + out
            else:
                out = out + extra
            continue

    return out


def _records_from_source(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        records = value.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


def _flatten_tree(items: list[Any], cfg: dict[str, Any]) -> list[Any]:
    children_path = str(cfg.get("children_path", "$.children[*]"))
    item_path = cfg.get("item_path")
    include_path = cfg.get("include_path")
    include_equals = cfg.get("include_equals")
    include_in = cfg.get("include_in")
    depth_path = cfg.get("depth_path")
    depth_field = str(cfg.get("depth_field", "__depth"))
    indent_field = cfg.get("indent_field")
    indent_unit = str(cfg.get("indent_unit", "  "))

    flattened: list[Any] = []

    def _match(node: Any) -> bool:
        if include_path is None:
            return True
        value = _eval_json_expr(node, str(include_path))
        if include_equals is not None:
            return str(value) == str(include_equals)
        if isinstance(include_in, list):
            return value in include_in
        return bool(value)

    def _depth(node: Any, fallback_depth: int) -> int:
        if isinstance(depth_path, str):
            value = _eval_json_expr(node, depth_path)
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
        return fallback_depth

    def _walk(node: Any, depth: int) -> None:
        current_depth = _depth(node, depth)

        if _match(node):
            entry = _eval_json_expr(node, str(item_path)) if isinstance(item_path, str) else node
            if isinstance(entry, dict):
                rec = dict(entry)
                rec[depth_field] = current_depth
                if indent_field:
                    rec[str(indent_field)] = indent_unit * max(current_depth, 0)
                flattened.append(rec)
            else:
                flattened.append(entry)

        children = _eval_json_expr(node, children_path)
        if children is None:
            return
        if not isinstance(children, list):
            children = [children]
        for child in children:
            _walk(child, current_depth + 1)

    for root in items:
        _walk(root, 0)

    return flattened


def _apply_item_ops(
    items: list[Any],
    item_ops: list[Any] | None,
) -> list[Any]:
    if not item_ops:
        return items

    out = list(items)
    for op in item_ops:
        if isinstance(op, dict) and "flatten_tree" in op:
            cfg = op.get("flatten_tree") or {}
            out = _flatten_tree(out, cfg)
    return out


def parse_records(source: Any, parse_spec: dict, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse records from a step output."""
    fmt = parse_spec.get("format", "json")

    if fmt == "html":
        body = source.get("body", "") if isinstance(source, dict) else str(source or "")
        records = parse_html(body, parse_spec, disable_truncate=_disable_truncate(ctx))
        return apply_post_ops(records, parse_spec.get("post_ops"), ctx)

    if fmt not in {"json", "json_list"}:
        raise ValueError(f"Unsupported parse format: {fmt}")

    if fmt == "json_list":
        raw_items = source if isinstance(source, list) else [source]
        parsed_items = []
        for it in raw_items:
            parsed = _request_to_json(it)
            if parsed is None:
                continue
            if isinstance(parsed, list):
                for sub in parsed:
                    if isinstance(sub, dict) and isinstance(it, dict):
                        sub = dict(sub)
                        if "index" in it:
                            sub.setdefault("__index", it["index"])
                        if "item" in it:
                            sub.setdefault("__item", it["item"])
                    parsed_items.append(sub)
            else:
                if isinstance(parsed, dict) and isinstance(it, dict):
                    parsed = dict(parsed)
                    if "index" in it:
                        parsed.setdefault("__index", it["index"])
                    if "item" in it:
                        parsed.setdefault("__item", it["item"])
                parsed_items.append(parsed)
        items = _extract_items(parsed_items, parse_spec.get("extract"))
    else:
        parsed = _request_to_json(source)
        if parsed is None:
            return []
        items = _extract_items(parsed, parse_spec.get("extract"))

    items = _apply_item_ops(items, parse_spec.get("item_ops"))

    fields = parse_spec.get("fields", [])
    if not fields:
        records = [it for it in items if isinstance(it, dict)]
        return apply_post_ops(records, parse_spec.get("post_ops"), ctx)

    records: list[dict[str, Any]] = []
    for item in items:
        record: dict[str, Any] = {}
        for field_spec in fields:
            name = field_spec["name"]
            value = _resolve_field_source(field_spec, item, ctx)

            template = field_spec.get("template")
            if template and value is not None:
                value = template.replace("{{value}}", str(value))

            value = _apply_ops(value, field_spec, item, ctx)
            record[name] = value
        records.append(record)

    return apply_post_ops(records, parse_spec.get("post_ops"), ctx)
