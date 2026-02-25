"""Core types for web2cli."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Request:
    method: str  # GET, POST, etc.
    url: str
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: str | dict | None = None
    content_type: str | None = None


@dataclass
class AdapterMeta:
    name: str
    domain: str
    base_url: str
    version: str
    description: str
    author: str
    transport: str = "http"
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
    request: dict  # raw YAML request section
    args: dict[str, CommandArg]
    response: dict  # raw YAML response section
    output: dict  # raw YAML output section


@dataclass
class AdapterSpec:
    meta: AdapterMeta
    auth: dict | None  # raw YAML auth section, None if no auth
    commands: dict[str, CommandSpec]


@dataclass
class Session:
    domain: str
    auth_type: str  # "cookies" | "token"
    data: dict  # {"cookies": {...}} or {"token": "..."}
    created_at: str = ""
    last_used: str = ""
