"""Provider plugin interfaces and built-ins."""

from web2cli.v2.providers.base import Provider
from web2cli.v2.providers.registry import get_provider

__all__ = ["Provider", "get_provider"]

