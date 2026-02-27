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

        # Check custom parser scripts exist
        response = cmd.response
        if response.get("parser") == "custom":
            script = response.get("script")
            if not script:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': custom parser missing 'script' field"
                )
            if not (adapter_dir / script).is_file():
                raise AdapterValidationError(
                    f"Command '{cmd_name}': parser script not found: {script}"
                )

        # Check custom builder scripts exist
        request = cmd.request
        if request.get("builder") == "custom":
            script = request.get("script")
            if not script:
                raise AdapterValidationError(
                    f"Command '{cmd_name}': custom builder missing 'script' field"
                )
            if not (adapter_dir / script).is_file():
                raise AdapterValidationError(
                    f"Command '{cmd_name}': builder script not found: {script}"
                )
