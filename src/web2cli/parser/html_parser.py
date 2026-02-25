"""HTML response parser using selectolax."""

from selectolax.parser import HTMLParser

from web2cli.parser.transforms import apply_transform


def parse_html(body: str, response_spec: dict) -> list[dict]:
    """Parse HTML response using CSS selectors from spec."""
    tree = HTMLParser(body)

    # Extract items matching the top-level selector
    extract_selector = response_spec.get("extract", "body")
    items = tree.css(extract_selector)

    if not items:
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

            if collect:
                # Collect multiple matching elements
                sub_nodes = item.css(path)
                values = [_extract_attr(n, attribute) for n in sub_nodes]
                values = [v for v in values if v]
                value = join_sep.join(values)
            else:
                # Single element
                node = item.css_first(path) if path else item
                value = _extract_attr(node, attribute) if node else None

            # Apply prefix
            if prefix and value:
                value = prefix + value

            # Apply transform
            transform = field_spec.get("transform")
            if transform:
                value = apply_transform(value, transform)

            # Apply truncation (display hint)
            truncate = field_spec.get("truncate")
            if truncate and value and isinstance(value, str) and len(value) > truncate:
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
