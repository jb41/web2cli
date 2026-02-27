"""Validate adapter specs."""

from pathlib import Path

from web2cli.types import AdapterSpec


class AdapterValidationError(Exception):
    pass


def validate_adapter(spec: AdapterSpec, adapter_dir: Path) -> None:
    """Validate an adapter spec.

    Checks:
    - Required meta fields present
    - Referenced custom scripts exist on disk
    """
    # Required meta fields
    for field in ("name", "domain", "base_url"):
        if not getattr(spec.meta, field, None):
            raise AdapterValidationError(
                f"Adapter missing required meta field: {field}"
            )

    if not spec.meta.spec_version.startswith("0.2"):
        raise AdapterValidationError(
            "Only adapter spec_version 0.2 is supported"
        )

    # Validate commands
    for cmd_name, cmd in spec.commands.items():
        # Validate command args
        stdin_count = 0
        for arg_name, arg in cmd.args.items():
            if arg.type not in {"string", "int", "float", "bool", "flag", "string[]"}:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': arg '{arg_name}' has unsupported type "
                    f"'{arg.type}'. Supported: string, int, float, bool, flag, string[]"
                )

            if not isinstance(arg.source, list) or not arg.source:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': arg '{arg_name}' must define "
                    f"'source' as a non-empty list"
                )

            invalid_sources = [s for s in arg.source if s not in {"arg", "stdin"}]
            if invalid_sources:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': arg '{arg_name}' has invalid source(s) "
                    f"{invalid_sources}. Supported: arg, stdin"
                )

            if "stdin" in arg.source:
                stdin_count += 1

        if stdin_count > 1:
            raise AdapterValidationError(
                f"Command '{cmd_name}': only one argument can use 'stdin' source"
            )

        if not cmd.pipeline:
            raise AdapterValidationError(
                f"Command '{cmd_name}': pipeline is required for spec v0.2"
            )

        if not isinstance(cmd.pipeline, list):
            raise AdapterValidationError(
                f"Command '{cmd_name}': pipeline must be a list"
            )

        for idx, raw_step in enumerate(cmd.pipeline):
            if not isinstance(raw_step, dict):
                raise AdapterValidationError(
                    f"Command '{cmd_name}': pipeline step {idx} must be an object"
                )

            step_keys = [
                k for k in raw_step.keys()
                if k in {"request", "resolve", "fanout", "parse", "transform"}
            ]
            if len(step_keys) != 1:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': pipeline step {idx} must contain exactly "
                    f"one step type (request|resolve|fanout|parse|transform)"
                )
            step_type = step_keys[0]
            step_spec = raw_step.get(step_type) or {}

            if not isinstance(step_spec, dict):
                raise AdapterValidationError(
                    f"Command '{cmd_name}': {step_type} step {idx} must be an object"
                )

            if step_type == "resolve":
                resource_name = step_spec.get("resource")
                if not resource_name:
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': resolve step {idx} missing resource"
                    )
                if resource_name not in spec.resources:
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': resolve step {idx} references unknown "
                        f"resource '{resource_name}'"
                    )

            if step_type == "fanout":
                if "request" not in step_spec:
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': fanout step {idx} missing request block"
                    )
                if not isinstance(step_spec.get("request"), dict):
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': fanout step {idx} request must be an object"
                    )

            if step_type == "parse" and step_spec.get("parser") == "custom":
                script = step_spec.get("script")
                if not script:
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': parse step {idx} custom parser missing script"
                    )
                if not (adapter_dir / script).is_file():
                    raise AdapterValidationError(
                        f"Command '{cmd_name}': parse step {idx} parser script not found: {script}"
                    )
