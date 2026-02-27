"""Provider base class for v0.2 request generation."""

from __future__ import annotations

from typing import Any

from web2cli.types import AdapterSpec, Request, Session


class Provider:
    """Provider plugin contract."""

    name: str = ""

    def build_request(
        self,
        spec: dict[str, Any],
        ctx: dict[str, Any],
        adapter: AdapterSpec,
        session: Session | None,
    ) -> Request:
        raise NotImplementedError

