"""Shared value transforms used by JSON and HTML parsers."""

import math
import re
from datetime import datetime, timezone


def apply_transform(value, transform: str):
    """Apply a named transform to a value."""
    if value is None:
        return value

    if transform == "round":
        try:
            return round(float(value))
        except (ValueError, TypeError):
            return value

    if transform == "int":
        try:
            return int(float(str(value).replace(",", "")))
        except (ValueError, TypeError):
            return value

    if transform == "lowercase":
        return str(value).lower()

    if transform == "uppercase":
        return str(value).upper()

    if transform == "strip_html":
        text = re.sub(r"<[^>]+>", " ", str(value))
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#39;", "'", text)
        text = re.sub(r"&nbsp;", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    if transform == "timestamp":
        return _parse_timestamp(value)

    if transform.startswith("truncate:"):
        try:
            n = int(transform.split(":")[1])
            s = str(value)
            return s[:n] + "..." if len(s) > n else s
        except (ValueError, IndexError):
            return value

    return value


def _parse_timestamp(value) -> str:
    """Convert various timestamp formats to readable string."""
    # Unix timestamp (int or float)
    if isinstance(value, (int, float)):
        if value > 1e12:
            value = value / 1000  # milliseconds
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return str(value)

    # ISO string
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        return value

    return str(value)
