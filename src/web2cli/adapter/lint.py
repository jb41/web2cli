"""Semantic adapter linter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from web2cli.types import AdapterSpec
from web2cli.providers import get_provider

_TPL_RE = re.compile(r"\{\{([^{}]+)\}\}")

_VALID_AUTH_TYPES = {"cookies", "token"}
_VALID_AUTH_INJECT_TARGETS = {"header", "query", "cookie", "form"}
_VALID_BODY_ENCODINGS = {"json", "form", "text", "bytes"}
_VALID_PARSE_FORMATS = {"json", "json_list", "html"}
_VALID_FIELD_OPS = {"map_lookup", "regex_replace", "append_urls", "join", "add", "template"}
_VALID_ITEM_OPS = {"flatten_tree"}
_VALID_POST_OPS = {"reverse", "sort", "limit", "filter_not_empty", "concat"}
_VALID_TRANSFORMS = {
    "round",
    "int",
    "lowercase",
    "uppercase",
    "strip_html",
    "timestamp",
    "x_datetime",
    "x_date",
}


@dataclass
class LintIssue:
    level: str  # error | warning
    path: str
    message: str


def lint_adapter(spec: AdapterSpec) -> list[LintIssue]:
    """Run semantic lint checks for a loaded adapter."""
    issues: list[LintIssue] = []

    _lint_meta(spec, issues)
    _lint_auth(spec, issues)
    _lint_resources_structure(spec, issues)
    _lint_commands(spec, issues)
    return issues


def _lint_meta(spec: AdapterSpec, issues: list[LintIssue]) -> None:
    if not spec.meta.spec_version.startswith("0.2"):
        _err(
            issues,
            "meta.spec_version",
            f"expected spec_version 0.2, got '{spec.meta.spec_version}'",
        )


def _lint_auth(spec: AdapterSpec, issues: list[LintIssue]) -> None:
    if not spec.auth:
        return

    methods = spec.auth.get("methods", [])
    if not isinstance(methods, list):
        _err(issues, "auth.methods", "must be a list")
        return

    for idx, method in enumerate(methods):
        path = f"auth.methods[{idx}]"
        if not isinstance(method, dict):
            _err(issues, path, "must be an object")
            continue

        mtype = str(method.get("type", "")).lower()
        if mtype and mtype not in _VALID_AUTH_TYPES:
            _err(issues, f"{path}.type", f"unsupported type '{mtype}'")

        inject = method.get("inject")
        if inject is None:
            continue
        if not isinstance(inject, dict):
            _err(issues, f"{path}.inject", "must be an object")
            continue

        target = str(inject.get("target", "")).lower()
        if target not in _VALID_AUTH_INJECT_TARGETS:
            _err(
                issues,
                f"{path}.inject.target",
                f"unsupported target '{target}', expected one of "
                f"{sorted(_VALID_AUTH_INJECT_TARGETS)}",
            )
        if not inject.get("key"):
            _err(issues, f"{path}.inject.key", "is required when inject is set")


def _lint_resources_structure(spec: AdapterSpec, issues: list[LintIssue]) -> None:
    for resource_name, resource_spec in spec.resources.items():
        path = f"resources.{resource_name}"
        if not isinstance(resource_spec, dict):
            _err(issues, path, "must be an object")
            continue

        request_spec = resource_spec.get("request")
        if isinstance(request_spec, dict):
            _lint_provider(request_spec, f"{path}.request", issues)
            _lint_request_encoding(request_spec, f"{path}.request", issues)

        paginate = resource_spec.get("paginate")
        if isinstance(paginate, dict):
            location = paginate.get("cursor_location")
            if location and str(location).lower() not in {"params", "body"}:
                _err(
                    issues,
                    f"{path}.paginate.cursor_location",
                    "must be params or body",
                )


def _lint_commands(spec: AdapterSpec, issues: list[LintIssue]) -> None:
    for cmd_name, cmd in spec.commands.items():
        cmd_path = f"commands.{cmd_name}"
        arg_names = set(cmd.args.keys())
        known_steps: set[str] = set()
        all_steps: set[str] = set()

        for idx, raw_step in enumerate(cmd.pipeline):
            step_path = f"{cmd_path}.pipeline[{idx}]"
            if not isinstance(raw_step, dict):
                continue

            step_type = _step_type(raw_step)
            if step_type is None:
                continue
            step_spec = raw_step.get(step_type) or {}
            if not isinstance(step_spec, dict):
                continue

            step_name = str(step_spec.get("name") or raw_step.get("name") or f"{step_type}_{idx}")
            if step_name in all_steps:
                _err(issues, f"{step_path}.{step_type}.name", f"duplicate step name '{step_name}'")

            if step_type == "request":
                _lint_request_spec(
                    step_spec, f"{step_path}.request", issues, arg_names, known_steps
                )
            elif step_type == "resolve":
                _lint_resolve_step(
                    spec,
                    step_spec,
                    f"{step_path}.resolve",
                    issues,
                    arg_names,
                    known_steps,
                )
            elif step_type == "fanout":
                _lint_fanout_step(
                    step_spec,
                    f"{step_path}.fanout",
                    issues,
                    arg_names,
                    known_steps,
                )
            elif step_type == "parse":
                _lint_parse_step(
                    step_spec,
                    f"{step_path}.parse",
                    issues,
                    arg_names,
                    known_steps,
                )
            elif step_type == "transform":
                _lint_transform_step(
                    step_spec,
                    f"{step_path}.transform",
                    issues,
                    arg_names,
                    known_steps,
                )

            all_steps.add(step_name)
            known_steps.add(step_name)

        from_step = cmd.output.get("from_step")
        if from_step and from_step not in all_steps:
            _err(
                issues,
                f"{cmd_path}.output.from_step",
                f"unknown step '{from_step}'",
            )


def _lint_resolve_step(
    spec: AdapterSpec,
    step_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    _lint_templates(step_spec, path, issues, arg_names, known_steps)

    resource_name = step_spec.get("resource")
    if not isinstance(resource_name, str) or not resource_name:
        return

    resource_spec = spec.resources.get(resource_name)
    if not isinstance(resource_spec, dict):
        return

    response_spec = resource_spec.get("response") or resource_spec.get("parse")
    if isinstance(response_spec, dict):
        field_names = _field_names(response_spec)
        by = step_spec.get("by")
        value = step_spec.get("value")
        if field_names and isinstance(by, str) and by not in field_names:
            _err(
                issues,
                f"{path}.by",
                f"field '{by}' is not produced by resource '{resource_name}'",
            )
        if field_names and isinstance(value, str) and value not in field_names:
            _err(
                issues,
                f"{path}.value",
                f"field '{value}' is not produced by resource '{resource_name}'",
            )

        _lint_parse_spec(
            response_spec,
            f"resources.{resource_name}.response",
            issues,
            arg_names,
            known_steps,
        )

    request_spec = resource_spec.get("request")
    if isinstance(request_spec, dict):
        _lint_request_spec(
            request_spec,
            f"resources.{resource_name}.request",
            issues,
            arg_names,
            known_steps,
        )


def _lint_fanout_step(
    step_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    _lint_templates(step_spec, path, issues, arg_names, known_steps)
    request_spec = step_spec.get("request")
    if isinstance(request_spec, dict):
        _lint_request_spec(
            request_spec, f"{path}.request", issues, arg_names, known_steps
        )


def _lint_parse_step(
    step_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    from_step = step_spec.get("from")
    if from_step and from_step not in known_steps:
        _err(
            issues,
            f"{path}.from",
            f"unknown step '{from_step}'",
        )
    _lint_parse_spec(step_spec, path, issues, arg_names, known_steps)


def _lint_transform_step(
    step_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    from_step = step_spec.get("from")
    if from_step and from_step not in known_steps:
        _err(
            issues,
            f"{path}.from",
            f"unknown step '{from_step}'",
        )
    _lint_templates(step_spec, path, issues, arg_names, known_steps)
    _lint_post_ops(step_spec.get("ops"), f"{path}.ops", issues, known_steps)


def _lint_request_spec(
    request_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    _lint_provider(request_spec, path, issues)
    _lint_request_encoding(request_spec, path, issues)
    _lint_templates(request_spec, path, issues, arg_names, known_steps)


def _lint_provider(
    request_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
) -> None:
    provider_name = request_spec.get("provider")
    if not provider_name:
        return
    try:
        get_provider(str(provider_name))
    except Exception as e:
        _err(issues, f"{path}.provider", str(e))


def _lint_request_encoding(
    request_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
) -> None:
    body = request_spec.get("body")
    if not isinstance(body, dict):
        return
    if "encoding" not in body:
        return
    encoding = str(body.get("encoding", "")).lower()
    if encoding not in _VALID_BODY_ENCODINGS:
        _err(
            issues,
            f"{path}.body.encoding",
            f"unsupported encoding '{encoding}'",
        )


def _lint_parse_spec(
    parse_spec: dict[str, Any],
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    parser = parse_spec.get("parser")
    if parser == "custom":
        _warn(
            issues,
            f"{path}.parser",
            "custom parser reduces portability; prefer declarative parse",
        )
        return

    fmt = str(parse_spec.get("format", "json")).lower()
    if fmt not in _VALID_PARSE_FORMATS:
        _err(issues, f"{path}.format", f"unsupported format '{fmt}'")

    _lint_templates(parse_spec, path, issues, arg_names, known_steps)
    _lint_item_ops(parse_spec.get("item_ops"), f"{path}.item_ops", issues)
    _lint_fields(parse_spec.get("fields"), f"{path}.fields", issues, known_steps)
    _lint_post_ops(parse_spec.get("post_ops"), f"{path}.post_ops", issues, known_steps)


def _lint_fields(
    fields: Any,
    path: str,
    issues: list[LintIssue],
    known_steps: set[str],
) -> None:
    if fields is None:
        return
    if not isinstance(fields, list):
        _err(issues, path, "must be a list")
        return

    for idx, field in enumerate(fields):
        fpath = f"{path}[{idx}]"
        if not isinstance(field, dict):
            _err(issues, fpath, "must be an object")
            continue

        transform = field.get("transform")
        if isinstance(transform, str) and not _is_known_transform(transform):
            _err(
                issues,
                f"{fpath}.transform",
                f"unsupported transform '{transform}'",
            )

        ops = field.get("ops")
        if ops is not None:
            if not isinstance(ops, list):
                _err(issues, f"{fpath}.ops", "must be a list")
            else:
                for op_idx, op in enumerate(ops):
                    _lint_field_op(op, f"{fpath}.ops[{op_idx}]", issues, known_steps)


def _lint_field_op(
    op: Any,
    path: str,
    issues: list[LintIssue],
    known_steps: set[str],
) -> None:
    if isinstance(op, str):
        if not _is_known_transform(op):
            _err(issues, path, f"unsupported transform '{op}'")
        return

    if not isinstance(op, dict) or len(op) != 1:
        _err(issues, path, "must be either a transform name or single-key object")
        return

    op_name, cfg = next(iter(op.items()))
    if op_name not in _VALID_FIELD_OPS:
        _err(issues, path, f"unsupported field op '{op_name}'")
        return

    if op_name == "map_lookup" and isinstance(cfg, dict):
        expr = cfg.get("from")
        if isinstance(expr, str):
            _lint_ctx_expression(expr, f"{path}.map_lookup.from", issues, known_steps)


def _lint_item_ops(
    ops: Any,
    path: str,
    issues: list[LintIssue],
) -> None:
    if ops is None:
        return
    if not isinstance(ops, list):
        _err(issues, path, "must be a list")
        return

    for idx, op in enumerate(ops):
        ipath = f"{path}[{idx}]"
        if not isinstance(op, dict) or len(op) != 1:
            _err(issues, ipath, "must be a single-key object")
            continue
        name = next(iter(op.keys()))
        if name not in _VALID_ITEM_OPS:
            _err(issues, ipath, f"unsupported item op '{name}'")


def _lint_post_ops(
    ops: Any,
    path: str,
    issues: list[LintIssue],
    known_steps: set[str],
) -> None:
    if ops is None:
        return
    if not isinstance(ops, list):
        _err(issues, path, "must be a list")
        return

    for idx, op in enumerate(ops):
        opath = f"{path}[{idx}]"
        if isinstance(op, str):
            if op != "reverse":
                _err(issues, opath, f"unsupported post op '{op}'")
            continue

        if not isinstance(op, dict) or len(op) != 1:
            _err(issues, opath, "must be 'reverse' or single-key object")
            continue

        name, cfg = next(iter(op.items()))
        if name not in _VALID_POST_OPS:
            _err(issues, opath, f"unsupported post op '{name}'")
            continue

        if name == "concat":
            if not isinstance(cfg, dict):
                _err(issues, f"{opath}.concat", "must be an object")
                continue
            step_names = cfg.get("steps", [])
            if isinstance(step_names, str):
                step_names = [step_names]
            if not isinstance(step_names, list):
                _err(issues, f"{opath}.concat.steps", "must be a list of step names")
                continue
            for sid, step_name in enumerate(step_names):
                if not isinstance(step_name, str):
                    _err(issues, f"{opath}.concat.steps[{sid}]", "must be a string")
                    continue
                if step_name not in known_steps:
                    _err(
                        issues,
                        f"{opath}.concat.steps[{sid}]",
                        f"unknown step '{step_name}'",
                    )


def _lint_templates(
    value: Any,
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    for expr, expr_path in _iter_templates(value, path):
        _lint_template_expr(expr, expr_path, issues, arg_names, known_steps)


def _iter_templates(value: Any, path: str):
    if isinstance(value, str):
        for match in _TPL_RE.finditer(value):
            yield match.group(1).strip(), path
        return

    if isinstance(value, list):
        for idx, item in enumerate(value):
            yield from _iter_templates(item, f"{path}[{idx}]")
        return

    if isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            yield from _iter_templates(item, key_path)


def _lint_template_expr(
    expr: str,
    path: str,
    issues: list[LintIssue],
    arg_names: set[str],
    known_steps: set[str],
) -> None:
    root = _expr_root(expr)
    if root is None:
        return

    if root == "args":
        match = re.match(r"^\s*args\.([A-Za-z_][A-Za-z0-9_]*)", expr)
        if match and match.group(1) not in arg_names:
            _err(issues, path, f"template references unknown arg '{match.group(1)}'")
        return

    if root == "steps":
        match = re.match(r"^\s*steps\.([A-Za-z_][A-Za-z0-9_]*)", expr)
        if match and match.group(1) not in known_steps:
            _err(issues, path, f"template references unknown step '{match.group(1)}'")
        return

    if root in {"item", "index", "auth", "value"}:
        return

    # Short-form arg expression: {{query}}
    if root in arg_names:
        return


def _lint_ctx_expression(
    expr: str,
    path: str,
    issues: list[LintIssue],
    known_steps: set[str],
) -> None:
    match = re.match(r"^\s*steps\.([A-Za-z_][A-Za-z0-9_]*)", expr)
    if match and match.group(1) not in known_steps:
        _err(issues, path, f"references unknown step '{match.group(1)}'")


def _expr_root(expr: str) -> str | None:
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)", expr)
    return match.group(1) if match else None


def _is_known_transform(name: str) -> bool:
    if name in _VALID_TRANSFORMS:
        return True
    if name.startswith("truncate:"):
        return True
    return False


def _field_names(parse_spec: dict[str, Any]) -> set[str]:
    fields = parse_spec.get("fields")
    if not isinstance(fields, list):
        return set()
    names = set()
    for field in fields:
        if isinstance(field, dict) and isinstance(field.get("name"), str):
            names.add(field["name"])
    return names


def _step_type(raw_step: dict[str, Any]) -> str | None:
    for key in ("request", "resolve", "fanout", "parse", "transform"):
        if key in raw_step:
            return key
    return None


def _err(issues: list[LintIssue], path: str, message: str) -> None:
    issues.append(LintIssue(level="error", path=path, message=message))


def _warn(issues: list[LintIssue], path: str, message: str) -> None:
    issues.append(LintIssue(level="warning", path=path, message=message))
