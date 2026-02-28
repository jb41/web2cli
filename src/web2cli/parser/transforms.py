"""Shared value transforms used by JSON and HTML parsers."""

import math
import re
from datetime import datetime, timezone


def apply_transform(value, transform: str, disable_truncate: bool = False):
    """Apply a named transform to a value."""
    if value is None:
        return value

    if transform == "round":
        try:
            return round(float(value))
        except (ValueError, TypeError):
            return value

    if transform == "int":
        text = str(value).strip().lower().replace(",", "")
        if text.endswith("k"):
            try:
                return int(float(text[:-1]) * 1000)
            except (ValueError, TypeError):
                pass
        if text.endswith("m"):
            try:
                return int(float(text[:-1]) * 1000000)
            except (ValueError, TypeError):
                pass
        try:
            return int(float(text))
        except (ValueError, TypeError):
            m = re.search(r"-?\d[\d,]*", text)
            if m:
                try:
                    return int(m.group(0).replace(",", ""))
                except ValueError:
                    return value
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

    if transform == "x_datetime":
        return _parse_twitter_datetime(value)

    if transform == "x_date":
        full = _parse_twitter_datetime(value)
        if isinstance(full, str) and len(full) >= 10:
            return full[:10]
        return full

    if transform.startswith("truncate:"):
        if disable_truncate:
            return value
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
        # numeric string (unix seconds / milliseconds)
        if re.fullmatch(r"\d+(\.\d+)?", value.strip()):
            try:
                num = float(value.strip())
                if num > 1e12:
                    num = num / 1000
                dt = datetime.fromtimestamp(num, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                pass

        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        return value

    return str(value)


def _parse_twitter_datetime(value) -> str:
    """Convert X/Twitter datetime to readable format."""
    if not isinstance(value, str):
        return str(value)
    try:
        dt = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value
