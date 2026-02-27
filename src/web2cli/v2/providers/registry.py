"""Provider registry."""

from __future__ import annotations

from web2cli.v2.providers.base import Provider

_PROVIDERS: dict[str, Provider] = {}
_BUILTINS_REGISTERED = False


def register_provider(provider: Provider) -> None:
    if not provider.name:
        raise ValueError("Provider must have a name")
    _PROVIDERS[provider.name] = provider


def _register_builtins_once() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return

    # Import side effect registers built-ins.
    from web2cli.v2.providers import x_graphql  # noqa: F401

    _BUILTINS_REGISTERED = True


def get_provider(name: str) -> Provider:
    _register_builtins_once()
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Unknown provider: {name}")
    return provider
