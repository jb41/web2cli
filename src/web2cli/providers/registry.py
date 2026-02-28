"""Provider registry."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from web2cli.providers.base import Provider
from web2cli.types import AdapterSpec

_PROVIDERS: dict[str, Provider] = {}
_BUILTINS_REGISTERED = False
_DYNAMIC_MODULES_LOADED: set[str] = set()

_BUILTIN_ADAPTERS_DIR = Path(__file__).resolve().parents[3] / "adapters"
_USER_ADAPTERS_DIR = Path.home() / ".web2cli" / "adapters"


def register_provider(provider: Provider) -> None:
    if not provider.name:
        raise ValueError("Provider must have a name")
    _PROVIDERS[provider.name] = provider


def _register_builtins_once() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return

    _BUILTINS_REGISTERED = True


def _safe_ident(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value)


def _load_provider_module(module_path: Path, key: str) -> None:
    if key in _DYNAMIC_MODULES_LOADED:
        return
    if not module_path.is_file():
        return

    module_name = f"web2cli_dynamic_provider_{_safe_ident(key)}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        return

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DYNAMIC_MODULES_LOADED.add(key)


def _load_from_adapter(adapter: AdapterSpec, provider_name: str) -> None:
    if adapter.adapter_dir is None:
        return
    provider_path = adapter.adapter_dir / "providers" / f"{provider_name}.py"
    key = f"{adapter.meta.domain}:{provider_name}:{provider_path}"
    _load_provider_module(provider_path, key)


def _load_from_known_adapter_dirs(provider_name: str) -> None:
    for base in (_BUILTIN_ADAPTERS_DIR, _USER_ADAPTERS_DIR):
        if not base.is_dir():
            continue
        for adapter_dir in base.iterdir():
            provider_path = adapter_dir / "providers" / f"{provider_name}.py"
            key = f"{adapter_dir}:{provider_name}:{provider_path}"
            _load_provider_module(provider_path, key)


def get_provider(name: str, adapter: AdapterSpec | None = None) -> Provider:
    _register_builtins_once()
    provider = _PROVIDERS.get(name)

    if provider is None and adapter is not None:
        _load_from_adapter(adapter, name)
        provider = _PROVIDERS.get(name)

    if provider is None:
        _load_from_known_adapter_dirs(name)
        provider = _PROVIDERS.get(name)

    if provider is None:
        raise ValueError(f"Unknown provider: {name}")
    return provider
