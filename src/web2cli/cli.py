"""CLI entry point for web2cli."""

import sys

import typer
from rich.console import Console
from typer.core import TyperGroup

from web2cli import __version__
from web2cli.adapter.loader import AdapterNotFound, load_adapter, list_adapters
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
    help="Every website is a command.",
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


def print_adapter_info(adapter: AdapterSpec) -> None:
    aliases = ", ".join(adapter.meta.aliases)
    err.print(f"\n[bold]{adapter.meta.name}[/bold] — {adapter.meta.description}")
    if aliases:
        err.print(f"  aliases: {aliases}")
    err.print(f"\n[bold]Commands:[/bold]")
    for name, cmd in adapter.commands.items():
        err.print(f"  {name:15} {cmd.description}")
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
            err.print(f"  --{name:15} {arg.type:10} {desc}{enum_str}  ({req})")
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
) -> None:
    """Execute an adapter command."""
    # Load adapter
    try:
        adapter = load_adapter(domain)
    except AdapterNotFound as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # No command → show adapter info
    if command is None or "--help" in ctx.args:
        if command and "--help" in ctx.args and command in adapter.commands:
            print_command_help(adapter, adapter.commands[command])
        else:
            print_adapter_info(adapter)
        raise typer.Exit(0)

    # Resolve command
    if command not in adapter.commands:
        err.print(f"[red]Unknown command '{command}' for {adapter.meta.domain}[/red]")
        err.print(f"Available: {', '.join(adapter.commands.keys())}")
        raise typer.Exit(1)

    cmd_spec = adapter.commands[command]

    # Parse dynamic args from ctx.args
    command_args, extra_globals = parse_dynamic_args(ctx.args, cmd_spec.args)
    validate_command_args(command_args, cmd_spec.args)

    # Build global flags dict
    global_flags = {
        "format": output_format,
        "fields": fields.split(",") if fields else None,
        "raw": raw,
        "verbose": verbose,
        "no_color": no_color,
    }
    for k, v in extra_globals.items():
        if k not in global_flags:
            global_flags[k] = v

    # TODO: Steps 4-8 will wire the actual execution pipeline here
    err.print(f"[dim]adapter={adapter.meta.domain} command={command}[/dim]")
    err.print(f"[dim]args={command_args}[/dim]")
    err.print(f"[dim]global_flags={global_flags}[/dim]")


# ---------------------------------------------------------------------------
# Subcommand: web2cli adapters list|info
# ---------------------------------------------------------------------------


adapters_app = typer.Typer(name="adapters", help="Manage adapters")
app.add_typer(adapters_app)


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
# Subcommand: web2cli login (placeholder for Step 10)
# ---------------------------------------------------------------------------


@app.command("login")
def login_command(
    domain: str = typer.Argument(..., help="Domain to authenticate"),
    cookies: str = typer.Option(None, "--cookies", help='Cookies string "k=v; k2=v2"'),
    cookie_file: str = typer.Option(None, "--cookie-file", help="Path to cookies JSON"),
    token: str = typer.Option(None, "--token", help="Auth token"),
) -> None:
    """Save authentication session for a domain."""
    err.print("[yellow]Login not yet implemented (Step 10)[/yellow]")
    raise typer.Exit(1)


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
