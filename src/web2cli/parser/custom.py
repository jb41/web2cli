"""Dynamic import and execution of custom parser scripts."""

import importlib.util
from pathlib import Path


def parse_custom(
    script_path: str,
    adapter_dir: Path,
    status_code: int,
    headers: dict,
    body: str,
    args: dict,
) -> list[dict]:
    """Import and call a custom parser script."""
    full_path = adapter_dir / script_path
    spec = importlib.util.spec_from_file_location("custom_parser", full_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.parse(status_code, headers, body, args)
