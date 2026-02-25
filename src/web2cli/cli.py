"""CLI entry point for web2cli."""

import typer

app = typer.Typer(
    name="web2cli",
    help="Every website is a command.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    if version:
        from web2cli import __version__

        typer.echo(f"web2cli {__version__}")
        raise typer.Exit()
