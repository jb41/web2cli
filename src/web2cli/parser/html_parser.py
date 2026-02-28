"""HTML response parser using selectolax."""

import sys

from selectolax.parser import HTMLParser

from web2cli.parser.transforms import apply_transform

# Page titles that indicate bot/CAPTCHA blocking
_BLOCK_SIGNALS = ("human verification", "captcha", "access denied", "just a moment")


def parse_html(body: str, response_spec: dict, disable_truncate: bool = False) -> list[dict]:
    """Parse HTML response using CSS selectors from spec."""
    tree = HTMLParser(body)

    # Extract items matching the top-level selector
    extract_selector = response_spec.get("extract", "body")
    items = tree.css(extract_selector)

    if not items:
        # Detect CAPTCHA / bot-blocking pages
        title_el = tree.css_first("title")
        if title_el:
            title = title_el.text(strip=True).lower()
            if any(s in title for s in _BLOCK_SIGNALS):
                print(
                    f"Blocked by site ({title_el.text(strip=True)}). "
                    "Try again later or use `web2cli login` to add cookies.",
                    file=sys.stderr,
                )
        return []

    fields = response_spec.get("fields", [])
    if not fields:
        return [{"text": node.text(strip=True)} for node in items]

    records = []
    for item in items:
        record = {}
        for field_spec in fields:
            name = field_spec["name"]
            path = field_spec.get("path", "")
            attribute = field_spec.get("attribute", "text")
            collect = field_spec.get("collect", False)
            join_sep = field_spec.get("join", ", ")
            prefix = field_spec.get("prefix", "")
            relative = field_spec.get("relative", "self")

            target = item
            if relative == "next":
                target = _next_element(item.next)
            elif relative == "parent":
                target = item.parent

            if collect:
                # Collect multiple matching elements
                sub_nodes = target.css(path) if target else []
                values = [_extract_attr(n, attribute) for n in sub_nodes]
                values = [v for v in values if v]
                value = join_sep.join(values)
            else:
                # Single element
                node = target.css_first(path) if (target and path) else target
                value = _extract_attr(node, attribute) if node else None

            # Apply prefix
            if prefix and value:
                value = prefix + value

            # Apply transform
            transform = field_spec.get("transform")
            if transform:
                value = apply_transform(value, transform, disable_truncate=disable_truncate)

            # Apply truncation (display hint)
            truncate = field_spec.get("truncate")
            if (
                not disable_truncate
                and truncate
                and value
                and isinstance(value, str)
                and len(value) > truncate
            ):
                value = value[:truncate] + "..."

            # Default fallback
            if value is None:
                value = field_spec.get("default")

            record[name] = value
        records.append(record)

    return records


def _extract_attr(node, attribute: str) -> str | None:
    """Extract an attribute value from a selectolax node."""
    if node is None:
        return None
    if attribute == "text":
        return node.text(strip=True) or None
    return node.attributes.get(attribute)


def _next_element(node):
    """Return next element-like node, skipping text/whitespace nodes."""
    cur = node
    while cur is not None and not hasattr(cur, "css_first"):
        cur = cur.next
    return cur
