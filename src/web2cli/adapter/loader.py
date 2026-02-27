"""Find and load adapter specs for a given domain or alias."""

from pathlib import Path

import yaml

from web2cli.adapter.validator import validate_adapter
from web2cli.types import AdapterMeta, AdapterSpec, CommandArg, CommandSpec

# Built-in adapters ship with the package (project root / adapters/)
_BUILTIN_ADAPTERS_DIR = Path(__file__).resolve().parents[3] / "adapters"

# User-installed adapters live in ~/.web2cli/adapters/
_USER_ADAPTERS_DIR = Path.home() / ".web2cli" / "adapters"


class AdapterNotFound(Exception):
    pass


def _find_adapter_dir(domain_or_alias: str) -> tuple[Path, str]:
    """Find the adapter directory for a domain or alias.

    Returns (adapter_dir, resolved_domain).
    Searches built-in first, then user-installed.
    """
    search_dirs = [_BUILTIN_ADAPTERS_DIR, _USER_ADAPTERS_DIR]

    # First: try as a direct domain match
    for base in search_dirs:
        candidate = base / domain_or_alias
        if (candidate / "web2cli.yaml").is_file():
            return candidate, domain_or_alias

    # Second: scan all adapters for alias match
    for base in search_dirs:
        if not base.is_dir():
            continue
        for adapter_dir in base.iterdir():
            yaml_path = adapter_dir / "web2cli.yaml"
            if not yaml_path.is_file():
                continue
            with open(yaml_path) as f:
                spec = yaml.safe_load(f)
            aliases = spec.get("meta", {}).get("aliases", [])
            if domain_or_alias in aliases:
                return adapter_dir, spec["meta"]["domain"]

    raise AdapterNotFound(
        f"No adapter found for '{domain_or_alias}'. "
        f"Run 'web2cli adapters list' to see available adapters."
    )


def _parse_command_arg(name: str, raw: dict) -> CommandArg:
    """Parse a single command argument from YAML dict."""
    arg_type = raw.get("type", "string")
    # Be permissive for common synonym used in adapters/spec drafts.
    if arg_type == "integer":
        arg_type = "int"

    return CommandArg(
        name=name,
        type=arg_type,
        required=raw.get("required", False),
        default=raw.get("default"),
        description=raw.get("description", ""),
        source=raw.get("source", ["arg"]),
        enum=raw.get("enum"),
        min=raw.get("min"),
        max=raw.get("max"),
    )


def _parse_command(name: str, raw: dict) -> CommandSpec:
    """Parse a single command from YAML dict."""
    raw_args = raw.get("args", {})
    args = {k: _parse_command_arg(k, v) for k, v in raw_args.items()}

    return CommandSpec(
        name=name,
        description=raw.get("description", ""),
        request=raw.get("request", {}),
        args=args,
        response=raw.get("response", {}),
        output=raw.get("output", {}),
    )


def _parse_meta(raw: dict) -> AdapterMeta:
    """Parse meta section from YAML dict."""
    return AdapterMeta(
        name=raw["name"],
        domain=raw["domain"],
        base_url=raw["base_url"],
        version=raw.get("version", "0.0.0"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        transport=raw.get("transport", "http"),
        impersonate=raw.get("impersonate"),
        aliases=raw.get("aliases", []),
        default_headers=raw.get("default_headers", {}),
    )


def _parse_adapter(raw: dict) -> AdapterSpec:
    """Parse full adapter spec from YAML dict."""
    meta = _parse_meta(raw["meta"])
    auth = raw.get("auth")
    commands_raw = raw.get("commands", {})
    commands = {k: _parse_command(k, v) for k, v in commands_raw.items()}

    return AdapterSpec(meta=meta, auth=auth, commands=commands)


def load_adapter(domain_or_alias: str) -> AdapterSpec:
    """Load adapter spec for a domain or alias.

    Raises AdapterNotFound if no adapter matches.
    """
    adapter_dir, domain = _find_adapter_dir(domain_or_alias)
    yaml_path = adapter_dir / "web2cli.yaml"

    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    spec = _parse_adapter(raw)
    spec.adapter_dir = adapter_dir
    validate_adapter(spec, adapter_dir)
    return spec


def list_adapters() -> list[AdapterSpec]:
    """List all available adapters (built-in + user-installed)."""
    adapters = []
    for base in [_BUILTIN_ADAPTERS_DIR, _USER_ADAPTERS_DIR]:
        if not base.is_dir():
            continue
        for adapter_dir in sorted(base.iterdir()):
            yaml_path = adapter_dir / "web2cli.yaml"
            if not yaml_path.is_file():
                continue
            with open(yaml_path) as f:
                raw = yaml.safe_load(f)
            adapters.append(_parse_adapter(raw))
    return adapters
