"""Output formatting: table, json, csv, plain, md."""

import csv
import io
import json

from rich import box
from rich.console import Console
from rich.table import Table


def format_output(
    records: list[dict],
    fmt: str = "table",
    fields: list[str] | None = None,
    no_color: bool = False,
) -> str:
    """Format records for stdout.

    Args:
        records: List of dicts to format.
        fmt: Output format — table, json, csv, plain.
        fields: Which fields to include (None = all).
        no_color: Disable colored output.
    """
    if not records:
        return ""

    # Resolve fields
    if not fields:
        fields = list(records[0].keys())

    # Filter records to only include requested fields
    filtered = [{k: r.get(k) for k in fields} for r in records]

    if fmt == "json":
        return _format_json(filtered)
    if fmt == "csv":
        return _format_csv(filtered, fields)
    if fmt == "plain":
        return _format_plain(filtered, fields)
    if fmt == "md":
        return _format_markdown(filtered, fields)
    return _format_table(filtered, fields, no_color)


def _format_table(records: list[dict], fields: list[str], no_color: bool) -> str:
    """Rich table output."""
    table_box = box.ASCII2 if no_color else box.HEAVY_HEAD
    table = Table(
        show_header=True,
        header_style=None if no_color else "bold",
        show_lines=False,
        pad_edge=False,
        box=table_box,
    )

    for field in fields:
        table.add_column(field.upper())

    for record in records:
        row = []
        for field in fields:
            val = record.get(field)
            cell = str(val) if val is not None else ""
            row.append(cell)
        table.add_row(*row)

    console = Console(no_color=no_color, force_terminal=not no_color)
    with console.capture() as capture:
        console.print(table)
    return capture.get().rstrip()


def _format_json(records: list[dict]) -> str:
    """JSON array output."""
    return json.dumps(records, indent=2, ensure_ascii=False)


def _format_csv(records: list[dict], fields: list[str]) -> str:
    """CSV output."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buf.getvalue().rstrip()


def _format_markdown(records: list[dict], fields: list[str]) -> str:
    """Markdown table output."""
    headers = [f.upper() for f in fields]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in fields) + " |")
    for record in records:
        cells = []
        for field in fields:
            val = record.get(field)
            cell = str(val) if val is not None else ""
            cell = cell.replace("|", "\\|")
            cells.append(cell)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _format_plain(records: list[dict], fields: list[str]) -> str:
    """Plain output — first field only, one per line. Best for piping."""
    first_field = fields[0]
    lines = []
    for record in records:
        val = record.get(first_field)
        if val is not None:
            lines.append(str(val))
    return "\n".join(lines)
