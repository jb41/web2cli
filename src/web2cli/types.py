"""Core types for web2cli."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Request:
    method: str  # GET, POST, etc.
    url: str
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: str | bytes | dict | None = None
    content_type: str | None = None


@dataclass
class AdapterMeta:
    name: str
    domain: str
    base_url: str
    version: str
    description: str
    author: str
    spec_version: str = "0.2"
    transport: str = "http"
    impersonate: str | None = None
    aliases: list[str] = field(default_factory=list)
    default_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class CommandArg:
    name: str
    type: str  # string, int, float, bool, flag, string[]
    required: bool = False
    default: Any = None
    description: str = ""
    source: list[str] = field(default_factory=lambda: ["arg"])
    enum: list[str] | None = None
    min: int | None = None
    max: int | None = None


@dataclass
class CommandSpec:
    name: str
    description: str
    args: dict[str, CommandArg]
    output: dict  # raw YAML output section
    pipeline: list[dict] = field(default_factory=list)  # v0.2 step pipeline


@dataclass
class AdapterSpec:
    meta: AdapterMeta
    auth: dict | None  # raw YAML auth section, None if no auth
    commands: dict[str, CommandSpec]
    resources: dict[str, dict] = field(default_factory=dict)  # v0.2 named resources
    adapter_dir: Path | None = None  # path to adapter directory on disk


@dataclass
class Session:
    domain: str
    auth_type: str  # "cookies" | "token"
    data: dict  # {"cookies": {...}} or {"token": "..."}
    created_at: str = ""
    last_used: str = ""
