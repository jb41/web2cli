"""CLI entry point for web2cli."""

import asyncio
import sys

import typer
from rich.console import Console
from typer.core import TyperGroup

from web2cli import __version__
from web2cli.adapter.loader import AdapterNotFound, load_adapter, list_adapters
from web2cli.auth.manager import (
    check_session,
    create_session,
    get_session,
    parse_cookie_file,
    parse_cookie_string,
    remove_session,
)
from web2cli.executor.builder import build_from_script, build_from_spec
from web2cli.executor.http import HttpError, execute
from web2cli.output.formatter import format_output
from web2cli.parser.custom import parse_custom
from web2cli.parser.html_parser import parse_html
from web2cli.parser.json_parser import parse_json
from web2cli.pipe import read_stdin
from web2cli.types import AdapterSpec, CommandArg, CommandSpec

err = Console(stderr=True)


# ---------------------------------------------------------------------------
# Custom TyperGroup: routes unknown subcommands to "run" handler
# ---------------------------------------------------------------------------


class DynamicGroup(TyperGroup):
    def parse_args(self, ctx, args):
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = ["run"] + args
        return super().parse_args(ctx, args)


app = typer.Typer(
    name="web2cli",
    help="Every website is a command.\n\nUsage: web2cli <domain> <command> [--args] [--format] [--fields] [--raw] [--verbose] [--no-color]",
    no_args_is_help=True,
    add_completion=False,
    cls=DynamicGroup,
)


# ---------------------------------------------------------------------------
# Dynamic argument parsing
# ---------------------------------------------------------------------------


def parse_dynamic_args(
    raw_args: list[str], arg_specs: dict[str, CommandArg]
) -> tuple[dict, dict]:
    """Parse CLI args against command arg definitions.

    Returns (command_args, extra_global_flags).
    """
    command_args: dict = {}
    global_flags: dict = {}
    i = 0

    while i < len(raw_args):
        token = raw_args[i]
        if not token.startswith("--"):
            i += 1
            continue

        key = token[2:].replace("-", "_")

        # Find matching arg spec — exact, then unambiguous prefix
        spec = arg_specs.get(key)
        if spec is None:
            matches = [n for n in arg_specs if n.startswith(key)]
            if len(matches) == 1:
                key = matches[0]
                spec = arg_specs[key]

        # Unknown arg → store as extra global flag
        if spec is None:
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("--"):
                global_flags[token[2:].replace("-", "_")] = raw_args[i + 1]
                i += 2
            else:
                global_flags[token[2:].replace("-", "_")] = True
                i += 1
            continue

        # Flag type — no value
        if spec.type == "flag":
            command_args[key] = True
            i += 1
            continue

        # string[] — collect repeated values
        if spec.type == "string[]":
            command_args.setdefault(key, [])
            i += 1
            if i < len(raw_args) and not raw_args[i].startswith("--"):
                command_args[key].append(raw_args[i])
                i += 1
            continue

        # All other types: consume next token as value
        i += 1
        if i >= len(raw_args):
            break
        raw_value = raw_args[i]
        i += 1

        if spec.type == "int":
            try:
                command_args[key] = int(raw_value)
            except ValueError:
                err.print(f"[red]--{key} expects an integer, got '{raw_value}'[/red]")
                raise typer.Exit(1)
        elif spec.type == "float":
            try:
                command_args[key] = float(raw_value)
            except ValueError:
                err.print(f"[red]--{key} expects a number, got '{raw_value}'[/red]")
                raise typer.Exit(1)
        elif spec.type == "bool":
            command_args[key] = raw_value.lower() in ("true", "1", "yes")
        else:
            command_args[key] = raw_value

    # Apply defaults
    for name, spec in arg_specs.items():
        if name not in command_args and spec.default is not None:
            command_args[name] = spec.default

    return command_args, global_flags


def validate_command_args(
    command_args: dict, arg_specs: dict[str, CommandArg]
) -> None:
    """Validate parsed args. Prints errors to stderr and exits on failure."""
    # Required
    missing = [
        name for name, spec in arg_specs.items()
        if spec.required and name not in command_args
    ]
    if missing:
        err.print(
            f"[red]Missing required arguments: "
            f"{', '.join('--' + m for m in missing)}[/red]"
        )
        raise typer.Exit(1)

    # Enum
    for name, spec in arg_specs.items():
        if spec.enum and name in command_args and command_args[name] not in spec.enum:
            err.print(
                f"[red]--{name} must be one of: {', '.join(spec.enum)}[/red]"
            )
            raise typer.Exit(1)

    # Min/max clamping
    for name, spec in arg_specs.items():
        if name in command_args and isinstance(command_args[name], (int, float)):
            if spec.min is not None and command_args[name] < spec.min:
                command_args[name] = spec.min
            if spec.max is not None and command_args[name] > spec.max:
                command_args[name] = spec.max


# ---------------------------------------------------------------------------
# Help helpers
# ---------------------------------------------------------------------------


GLOBAL_FLAGS_HELP = """\
[bold]Global flags:[/bold]
  --format, -f       Output format: table, json, csv, plain, md
  --fields           Comma-separated list of fields to display
  --sort             Override output sort field (if command doesn't use --sort)
  --sort-by          Override output sort field (always safe)
  --raw              Show raw HTTP response body
  --verbose          Show request URL, params, and timing
  --no-color         Disable colors and use ASCII table borders
  --no-header        Omit header row (csv only)"""


def print_adapter_info(adapter: AdapterSpec) -> None:
    aliases = ", ".join(adapter.meta.aliases)
    err.print(f"\n[bold]{adapter.meta.name}[/bold] — {adapter.meta.description}")
    if aliases:
        err.print(f"  aliases: {aliases}")
    err.print(f"\n[bold]Commands:[/bold]")
    for name, cmd in adapter.commands.items():
        err.print(f"  {name:15} {cmd.description}")
    err.print()
    err.print(GLOBAL_FLAGS_HELP)
    err.print()


def print_command_help(adapter: AdapterSpec, cmd: CommandSpec) -> None:
    err.print(
        f"\n[bold]web2cli {adapter.meta.name} {cmd.name}[/bold]"
        f" — {cmd.description}\n"
    )
    if not cmd.args:
        err.print("  (no arguments)")
    else:
        err.print("[bold]Arguments:[/bold]")
        for name, arg in cmd.args.items():
            req = "[red]required[/red]" if arg.required else f"default: {arg.default}"
            desc = arg.description or ""
            enum_str = f" [{', '.join(arg.enum)}]" if arg.enum else ""
            pipe_str = "  [dim]pipeable[/dim]" if "stdin" in arg.source else ""
            err.print(f"  --{name:15} {arg.type:10} {desc}{enum_str}  ({req}){pipe_str}")
    err.print()
    err.print(GLOBAL_FLAGS_HELP)
    err.print()


# ---------------------------------------------------------------------------
# Main command: web2cli <domain> <command> [--args]
# ---------------------------------------------------------------------------


@app.command(
    "run",
    hidden=True,
    context_settings={
        "allow_extra_args": True,
        "allow_interspersed_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
)
def run_command(
    ctx: typer.Context,
    domain: str = typer.Argument(..., help="Domain or adapter alias"),
    command: str = typer.Argument(None, help="Command to execute"),
    output_format: str = typer.Option(
        None, "--format", "-f", help="Output format (table|json|csv|plain)"
    ),
    fields: str = typer.Option(None, "--fields", help="Comma-separated fields"),
    raw: bool = typer.Option(False, "--raw", help="Show raw HTTP response"),
    verbose: bool = typer.Option(False, "--verbose", help="Show request details"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    no_header: bool = typer.Option(False, "--no-header", help="Omit header row (csv)"),
) -> None:
    """Execute an adapter command."""
    # Load adapter
    try:
        adapter = load_adapter(domain)
    except AdapterNotFound as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Help handling
    help_requested = "--help" in ctx.args or command == "--help"
    if command == "--help":
        command = None

    # No command → show adapter info
    if command is None or (help_requested and command not in adapter.commands):
        print_adapter_info(adapter)
        raise typer.Exit(0)

    # Command help
    if help_requested and command in adapter.commands:
        print_command_help(adapter, adapter.commands[command])
        raise typer.Exit(0)

    # Resolve command
    if command not in adapter.commands:
        err.print(f"[red]Unknown command '{command}' for {adapter.meta.domain}[/red]")
        err.print(f"Available: {', '.join(adapter.commands.keys())}")
        raise typer.Exit(1)

    cmd_spec = adapter.commands[command]

    # Parse dynamic args from ctx.args
    command_args, extra_globals = parse_dynamic_args(ctx.args, cmd_spec.args)

    # Merge extra globals
    for k, v in extra_globals.items():
        if k == "limit":
            try:
                extra_globals[k] = int(v)
            except (ValueError, TypeError):
                pass

    # --- Stdin injection ---
    stdin_value = read_stdin()
    if stdin_value:
        for arg_name, arg_spec in cmd_spec.args.items():
            if "stdin" in arg_spec.source and arg_name not in command_args:
                command_args[arg_name] = stdin_value
                break

    # Re-validate after stdin injection
    validate_command_args(command_args, cmd_spec.args)

    # --- Load session (if adapter supports auth) ---
    session = get_session(adapter.meta.domain, adapter.auth)

    # --- Build + Execute (with retry for custom builders) ---
    def _build():
        if cmd_spec.request.get("builder") == "custom":
            return build_from_script(
                cmd_spec.request["script"], adapter.adapter_dir, command_args, session
            )
        return build_from_spec(cmd_spec, command_args, session, adapter.meta)

    request = _build()
    try:
        status, resp_headers, body = asyncio.run(
            execute(request, verbose=verbose, impersonate=adapter.meta.impersonate)
        )
    except HttpError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Retry once for custom builders on client/server errors
    if status >= 400 and cmd_spec.request.get("builder") == "custom":
        if verbose:
            err.print(f"[yellow]Got {status}, retrying with _retry=True...[/yellow]")
        command_args["_retry"] = True
        request = _build()
        try:
            status, resp_headers, body = asyncio.run(
                execute(request, verbose=verbose, impersonate=adapter.meta.impersonate)
            )
        except HttpError as e:
            err.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    # --raw: dump raw response and exit
    if raw:
        print(body)
        raise typer.Exit(0)

    # --- Parse response ---
    response_spec = cmd_spec.response
    if response_spec.get("parser") == "custom":
        records = parse_custom(
            response_spec["script"], adapter.adapter_dir,
            status, resp_headers, body, command_args,
        )
    elif response_spec.get("format") == "html":
        records = parse_html(body, response_spec)
    else:
        records = parse_json(body, response_spec)

    if not records:
        err.print("[yellow]No results.[/yellow]")
        raise typer.Exit(0)

    # --- Sort ---
    output_spec = cmd_spec.output
    global_sort = extra_globals.get("sort_by")
    if global_sort is None:
        global_sort = extra_globals.get("sort")

    if isinstance(global_sort, bool):
        err.print("[red]--sort/--sort-by expects a field name[/red]")
        raise typer.Exit(1)

    sort_by = global_sort or output_spec.get("sort_by")
    sort_order = output_spec.get("sort_order", "desc")
    should_sort = bool(sort_by) and (
        bool(global_sort) or response_spec.get("parser") != "custom"
    )

    if should_sort and records:
        records.sort(
            key=lambda r: r.get(sort_by, 0) or 0,
            reverse=(sort_order == "desc"),
        )

    # --- Limit ---
    limit = extra_globals.get("limit")
    if limit is None:
        # Use command arg limit for post-processing cap too
        limit = command_args.get("limit")
    if limit:
        try:
            records = records[:int(limit)]
        except (ValueError, TypeError):
            pass

    # --- Format and output ---
    fmt = output_format or output_spec.get("default_format", "table")
    show_fields = (
        fields.split(",") if fields
        else output_spec.get("default_fields")
    )

    result = format_output(records, fmt, show_fields, no_color, no_header=no_header)
    if result:
        print(result)


# ---------------------------------------------------------------------------
# Subcommand: web2cli adapters list|info
# ---------------------------------------------------------------------------


adapters_app = typer.Typer(
    name="adapters", help="Manage adapters",
    invoke_without_command=True,
)
app.add_typer(adapters_app)


@adapters_app.callback()
def adapters_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@adapters_app.command("list")
def adapters_list() -> None:
    """List all available adapters."""
    for adapter in list_adapters():
        aliases = ", ".join(adapter.meta.aliases)
        alias_str = f" ({aliases})" if aliases else ""
        cmds = ", ".join(adapter.commands.keys())
        err.print(
            f"  [bold]{adapter.meta.domain}[/bold]{alias_str}"
            f" — {len(adapter.commands)} commands: {cmds}"
        )


@adapters_app.command("info")
def adapters_info(
    domain: str = typer.Argument(..., help="Domain or alias"),
) -> None:
    """Show details for an adapter."""
    try:
        adapter = load_adapter(domain)
    except AdapterNotFound as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    print_adapter_info(adapter)


# ---------------------------------------------------------------------------
# Subcommand: web2cli login / logout
# ---------------------------------------------------------------------------


@app.command("login")
def login_command(
    domain: str = typer.Argument(..., help="Domain or alias to authenticate"),
    cookies: str = typer.Option(None, "--cookies", help='Cookies string "k=v; k2=v2"'),
    cookie_file: str = typer.Option(None, "--cookie-file", help="Path to cookies JSON"),
    token: str = typer.Option(None, "--token", help="Auth token"),
    status: bool = typer.Option(False, "--status", help="Check login status"),
) -> None:
    """Save authentication session for a domain."""
    # Resolve alias → adapter domain
    try:
        adapter = load_adapter(domain)
        resolved_domain = adapter.meta.domain
    except AdapterNotFound:
        resolved_domain = domain

    # --status: show session info and exit
    if status:
        info = check_session(resolved_domain)
        if not info.get("exists"):
            err.print(f"[yellow]No session for {resolved_domain}[/yellow]")
            raise typer.Exit(1)
        err.print(f"[green]Logged in to {resolved_domain}[/green]")
        err.print(f"  type: {info.get('auth_type', '?')}")
        if info.get("cookie_keys"):
            err.print(f"  cookies: {', '.join(info['cookie_keys'])}")
        if info.get("has_token"):
            err.print("  token: present")
        if info.get("created_at"):
            err.print(f"  created: {info['created_at']}")
        raise typer.Exit(0)

    # Parse cookies from string or file
    parsed_cookies = None
    if cookies:
        parsed_cookies = parse_cookie_string(cookies)
    elif cookie_file:
        try:
            parsed_cookies = parse_cookie_file(cookie_file)
        except (OSError, ValueError) as e:
            err.print(f"[red]Failed to read cookie file: {e}[/red]")
            raise typer.Exit(1)

    if not parsed_cookies and not token:
        err.print("[red]Provide --cookies, --cookie-file, or --token[/red]")
        raise typer.Exit(1)

    # Warn about missing keys if adapter has an auth spec
    try:
        adapter = load_adapter(domain)
        if adapter.auth and parsed_cookies:
            for method in adapter.auth.get("methods", []):
                expected = method.get("keys", [])
                missing = [k for k in expected if k not in parsed_cookies]
                if missing:
                    err.print(
                        f"[yellow]Warning: adapter expects cookie keys "
                        f"{missing} but they were not provided[/yellow]"
                    )
    except AdapterNotFound:
        pass

    # Save session
    session = create_session(resolved_domain, cookies=parsed_cookies, token=token)
    err.print(f"[green]Session saved for {resolved_domain} ({session.auth_type})[/green]")


@app.command("logout")
def logout_command(
    domain: str = typer.Argument(..., help="Domain or alias to log out"),
) -> None:
    """Remove stored session for a domain."""
    try:
        adapter = load_adapter(domain)
        resolved_domain = adapter.meta.domain
    except AdapterNotFound:
        resolved_domain = domain

    if remove_session(resolved_domain):
        err.print(f"[green]Session removed for {resolved_domain}[/green]")
    else:
        err.print(f"[yellow]No session found for {resolved_domain}[/yellow]")


# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    if version:
        typer.echo(f"web2cli {__version__}")
        raise typer.Exit()
