"""Custom parser for Gmail inbox HTML response.

Gmail embeds inbox thread data as a double-escaped JSON string inside the
HTML/JS response under the key "sils". This parser extracts, unescapes,
and parses that structure into a flat list of thread records.

Thread data structure (after unescaping):
  data[0][0] = list of thread entries
  Each thread entry:
    [0] null
    [1] "thread-f:<id>"
    [2] sort key (descending timestamp complement)
    [3] subject
    [4] inner data array:
      [0] subject (duplicate)
      [1] snippet
      [2] timestamp (ms)
      [3] thread ref
      [4] messages array, each message:
        [0] "msg-f:<id>"
        [1] [type, email, display_name]
        [6] timestamp (ms)
        [9] snippet
        [10] labels (e.g. ["^all", "^i", "^u"])
"""

import json
from datetime import datetime, timezone


# Well-known Gmail label mappings
_LABEL_MAP = {
    "i": "inbox",
    "u": "unread",
    "all": "all",
    "st": "starred",
    "t": "trash",
    "s": "spam",
    "sm": "sent",
    "f": "draft",
    "imp": "important",
    "nt": "notes",
    "cff": "scheduled",
    "unsub": "unsubscribe",
    "oc_unsub": "one-click-unsub",
    "p_mtunsub": "mute-unsub",
    "fnas": "auto-classified",
    "ndpp": "not-displayed-in-promo",
    "sq_ig_i_personal": "personal",
}


def _find_sils_string(body: str) -> str | None:
    """Extract the double-escaped JSON string from the sils key."""
    marker = '"sils",null,"'
    idx = body.find(marker)
    if idx < 0:
        return None

    start = idx + len('"sils",null,')  # keep opening quote for json.loads
    pos = start + 1
    escape_count = 0

    while pos < len(body):
        c = body[pos]
        if c == "\\":
            escape_count += 1
        elif c == '"':
            if escape_count % 2 == 0:
                break
            escape_count = 0
        else:
            escape_count = 0
        pos += 1

    if pos >= len(body):
        return None

    raw = body[start : pos + 1]
    return json.loads(raw)


def _safe_get(arr, idx, default=None):
    """Safely index into a list."""
    if isinstance(arr, list) and len(arr) > idx:
        return arr[idx]
    return default


def _format_ts(timestamp_ms):
    """Convert ms timestamp to YYYY-MM-DD HH:MM string."""
    if not timestamp_ms or not isinstance(timestamp_ms, (int, float)):
        return ""
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""


def _clean_labels(raw_labels: list[str] | None) -> list[str]:
    """Strip ^ prefix and map known labels to human-readable names."""
    if not raw_labels:
        return []
    out = []
    for label in raw_labels:
        key = label.lstrip("^")
        mapped = _LABEL_MAP.get(key, key)
        out.append(mapped)
    return out


def _extract_threads(data: list) -> list[dict]:
    """Walk the parsed JSON structure and extract thread records."""
    threads_list = _safe_get(_safe_get(data, 0), 0)
    if not isinstance(threads_list, list):
        return []

    records = []
    for entry in threads_list:
        if not isinstance(entry, list) or len(entry) < 5:
            continue

        raw_thread_id = _safe_get(entry, 1, "")
        if not isinstance(raw_thread_id, str) or not raw_thread_id.startswith("thread-f:"):
            continue

        thread_id = raw_thread_id.replace("thread-f:", "")
        subject = _safe_get(entry, 3, "")
        inner = _safe_get(entry, 4)

        if not isinstance(inner, list):
            continue

        snippet = _safe_get(inner, 1, "")
        timestamp_ms = _safe_get(inner, 2, 0)
        messages = _safe_get(inner, 4, [])

        # Extract sender and labels from the first (most recent) message
        sender_email = ""
        sender_name = ""
        labels_raw = []
        message_id = ""

        if isinstance(messages, list) and messages:
            first_msg = messages[0]
            if isinstance(first_msg, list):
                raw_msg_id = _safe_get(first_msg, 0, "")
                if isinstance(raw_msg_id, str):
                    message_id = raw_msg_id.replace("msg-f:", "")

                sender_info = _safe_get(first_msg, 1)
                if isinstance(sender_info, list):
                    sender_email = _safe_get(sender_info, 1, "")
                    sender_name = _safe_get(sender_info, 2, "")

                labels_raw = _safe_get(first_msg, 10, [])

        if not isinstance(labels_raw, list):
            labels_raw = []

        unread = "^u" in labels_raw
        labels = _clean_labels(labels_raw)
        date = _format_ts(timestamp_ms)
        message_count = len(messages) if isinstance(messages, list) else 0

        records.append({
            "thread_id": thread_id,
            "message_id": message_id,
            "subject": subject or "",
            "snippet": snippet or "",
            "sender_email": sender_email or "",
            "sender_name": sender_name or "",
            "date": date,
            "timestamp": timestamp_ms,
            "unread": unread,
            "labels": ", ".join(labels),
            "message_count": message_count,
        })

    # Sort by timestamp descending (newest first)
    records.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
    return records


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Entry point called by the web2cli custom parser loader."""
    if status_code >= 400:
        return []

    unescaped = _find_sils_string(body)
    if not unescaped:
        return []

    try:
        data = json.loads(unescaped)
    except json.JSONDecodeError:
        return []

    return _extract_threads(data)
