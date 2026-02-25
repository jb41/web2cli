"""Stdin detection and reading for piped input."""

import sys


def read_stdin() -> str | None:
    """Read from stdin if data is being piped. Returns None if no pipe."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return None
