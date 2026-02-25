"""JSON response parser using jmespath."""

import json

import jmespath

from web2cli.parser.transforms import apply_transform


def _jmespath_expr(path: str) -> str:
    """Convert JSONPath-like syntax to jmespath.

    Handles common patterns:
      $.hits[*]  → hits[*]
      $.title    → title
      $          → @
    """
    if path == "$":
        return "@"
    if path.startswith("$."):
        return path[2:]
    return path


def parse_json(body: str, response_spec: dict) -> list[dict]:
    """Parse JSON response using spec's extract path and field mappings."""
    # Optional prefix stripping (e.g. ")]}'\n")
    strip_prefix = response_spec.get("strip_prefix")
    if strip_prefix and body.startswith(strip_prefix):
        body = body[len(strip_prefix):]

    data = json.loads(body)

    # Extract array of items
    extract = response_spec.get("extract", "$")
    expr = _jmespath_expr(extract)
    items = jmespath.search(expr, data)

    if items is None:
        return []

    # If extract points to a single object (not array), wrap it
    if isinstance(items, dict):
        items = [items]

    # Map fields
    fields = response_spec.get("fields", [])
    if not fields:
        # No field mapping — return raw items
        return items if isinstance(items, list) else [items]

    records = []
    for item in items:
        record = {}
        for field_spec in fields:
            name = field_spec["name"]
            path = field_spec.get("path", f"$.{name}")
            fexpr = _jmespath_expr(path)

            value = jmespath.search(fexpr, item)

            # Apply template (e.g. "https://example.com/item?id={{value}}")
            template = field_spec.get("template")
            if template and value is not None:
                value = template.replace("{{value}}", str(value))

            # Apply transform
            transform = field_spec.get("transform")
            if transform:
                value = apply_transform(value, transform)

            # Default fallback
            if value is None:
                value = field_spec.get("default")

            record[name] = value
        records.append(record)

    return records
