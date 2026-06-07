"""Command-line interface (CLI) for local Gitingest."""

# pylint: disable=no-value-for-parameter
from __future__ import annotations

import asyncio
from typing import TypedDict

import click
from typing_extensions import Unpack

from gitingest.config import MAX_FILE_SIZE, OUTPUT_FILE_NAME
from gitingest.entrypoint import ingest_async

# Import logging configuration first to intercept all logging
from gitingest.utils.logging_config import get_logger

# Initialize logger for this module
logger = get_logger(__name__)


class _CLIArgs(TypedDict):
    source: str
    max_size: int
    exclude_pattern: tuple[str, ...]
    include_pattern: tuple[str, ...]
    include_gitignored: bool
    output: str | None


@click.command()
@click.argument("source", type=str, default=".")
@click.option(
    "--max-size",
    "-s",
    default=MAX_FILE_SIZE,
    show_default=True,
    help="Maximum file size to process in bytes",
)
@click.option("--exclude-pattern", "-e", multiple=True, help="Shell-style patterns to exclude.")
@click.option(
    "--include-pattern",
    "-i",
    multiple=True,
    help="Shell-style patterns to include.",
)
@click.option(
    "--include-gitignored",
    is_flag=True,
    default=False,
    help="Include files matched by .gitignore and .gitingestignore",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output file path (default: digest.txt in current directory). Use '-' for stdout.",
)
def main(**cli_kwargs: Unpack[_CLIArgs]) -> None:
    """Run the CLI entry point to analyze a local directory and dump its contents.

    Examples
    --------
    Basic usage:
        $ gitingest
        $ gitingest /path/to/directory

    Output to stdout:
        $ gitingest -o -

    With filtering:
        $ gitingest -i "*.py" -e "*.log"
    """
    asyncio.run(_async_main(**cli_kwargs))


async def _async_main(
    source: str,
    *,
    max_size: int = MAX_FILE_SIZE,
    exclude_pattern: tuple[str, ...] | None = None,
    include_pattern: tuple[str, ...] | None = None,
    include_gitignored: bool = False,
    output: str | None = None,
) -> None:
    try:
        exclude_patterns = set(exclude_pattern) if exclude_pattern else set()
        include_patterns = set(include_pattern) if include_pattern else set()

        output_target = output if output is not None else OUTPUT_FILE_NAME

        if output_target == "-":
            click.echo("Analyzing source, preparing output for stdout...", err=True)
        else:
            click.echo(f"Analyzing source, output will be written to '{output_target}'...", err=True)

        summary, _, _ = await ingest_async(
            source,
            max_file_size=max_size,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            include_gitignored=include_gitignored,
            output=output_target,
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.Abort from exc

    if output_target == "-":  # stdout
        click.echo("\n--- Summary ---", err=True)
        click.echo(summary, err=True)
        click.echo("--- End Summary ---", err=True)
        click.echo("Analysis complete! Output sent to stdout.", err=True)
    else:  # file
        click.echo(f"Analysis complete! Output written to: {output_target}")
        click.echo("\nSummary:")
        click.echo(summary)


if __name__ == "__main__":
    main()
