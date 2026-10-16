"""Dynamic import and execution of custom parser scripts."""

import importlib.util
from pathlib import Path


class SecurityError(RuntimeError):
    """Raised for security policy violations."""


def parse_custom(
    script_path: str,
    adapter_dir: Path,
    status_code: int,
    headers: dict,
    body: str,
    args: dict,
) -> list[dict]:
    """Import and call a custom parser script."""
    if Path(script_path).is_absolute():
        raise SecurityError(f"Absolute script paths are forbidden: {script_path}")

    resolved_adapter_dir = adapter_dir.resolve()
    full_path = (adapter_dir / script_path).resolve()

    try:
        full_path.relative_to(resolved_adapter_dir)
    except ValueError:
        raise SecurityError(
            f"Path traversal detected: {script_path} escapes adapter directory"
        )

    if not full_path.is_file():
        raise FileNotFoundError(f"Parser script not found: {full_path}")

    spec = importlib.util.spec_from_file_location("custom_parser", full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec from {full_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "parse") or not callable(module.parse):
        raise AttributeError(f"Custom parser {script_path} must define a callable parse() function")

    return module.parse(status_code, headers, body, args)

