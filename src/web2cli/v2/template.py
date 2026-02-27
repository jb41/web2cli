"""Template rendering helpers for v0.2 specs."""

from __future__ import annotations

import re
from typing import Any

import jmespath

_TPL_RE = re.compile(r"\{\{([^{}]+)\}\}")


def resolve_expr(expr: str, ctx: dict[str, Any]) -> Any:
    """Resolve an expression against runtime context."""
    expr = expr.strip()
    value = jmespath.search(expr, ctx)
    if value is not None:
        return value

    # Short form: {{arg_name}} resolves from args.
    args = ctx.get("args", {})
    if expr in args:
        return args[expr]
    return ctx.get(expr)


def render_string(template: str, ctx: dict[str, Any]) -> Any:
    """Render a template string.

    If the full string is a single template expression, returns the resolved
    value as-is (preserving type). Otherwise returns a string with replacements.
    """
    match = _TPL_RE.fullmatch(template.strip())
    if match:
        return resolve_expr(match.group(1), ctx)

    def _replace(m: re.Match) -> str:
        value = resolve_expr(m.group(1), ctx)
        return "" if value is None else str(value)

    return _TPL_RE.sub(_replace, template)


def render_value(value: Any, ctx: dict[str, Any]) -> Any:
    """Recursively render templates in nested data."""
    if isinstance(value, str):
        return render_string(value, ctx)
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    return value
