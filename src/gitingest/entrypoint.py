"""Main entry point for ingesting a local source and processing its contents."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from gitingest.config import MAX_FILE_SIZE
from gitingest.ingestion import ingest_query
from gitingest.query_parser import parse_local_dir_path
from gitingest.schemas import IngestionQuery
from gitingest.utils.ignore_patterns import load_ignore_patterns
from gitingest.utils.logging_config import get_logger
from gitingest.utils.pattern_utils import process_patterns

# Initialize logger for this module
logger = get_logger(__name__)


async def ingest_async(
    source: str,
    *,
    max_file_size: int = MAX_FILE_SIZE,
    include_patterns: str | set[str] | None = None,
    exclude_patterns: str | set[str] | None = None,
    include_gitignored: bool = False,
    output: str | None = None,
) -> tuple[str, str, str]:
    """Ingest a local source path and process its contents."""
    logger.info("Starting local ingestion process", extra={"source": source})

    query = parse_local_dir_path(source)

    query.max_file_size = max_file_size
    query.ignore_patterns, query.include_patterns = process_patterns(
        exclude_patterns=exclude_patterns,
        include_patterns=include_patterns,
    )

    if not include_gitignored:
        logger.debug("Applying gitignore patterns")
        _apply_gitignores(query)

    logger.info("Processing files and generating output")
    summary, tree, content = ingest_query(query)

    if output:
        logger.debug("Writing output to file", extra={"output_path": output})
        await _write_output(tree, content=content, target=output)

    logger.info("Ingestion completed successfully")
    return summary, tree, content


def ingest(
    source: str,
    *,
    max_file_size: int = MAX_FILE_SIZE,
    include_patterns: str | set[str] | None = None,
    exclude_patterns: str | set[str] | None = None,
    include_gitignored: bool = False,
    output: str | None = None,
) -> tuple[str, str, str]:
    """Provide a synchronous wrapper around ``ingest_async``."""
    return asyncio.run(
        ingest_async(
            source=source,
            max_file_size=max_file_size,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            include_gitignored=include_gitignored,
            output=output,
        ),
    )


def _apply_gitignores(query: IngestionQuery) -> None:
    """Update ``query.ignore_patterns`` in-place."""
    for fname in (".gitignore", ".gitingestignore"):
        query.ignore_patterns.update(load_ignore_patterns(query.local_path, filename=fname))


async def _write_output(tree: str, content: str, target: str | None) -> None:
    """Write combined output to target (``"-"`` ⇒ stdout)."""
    data = f"{tree}\n{content}"
    loop = asyncio.get_running_loop()
    if target == "-":
        await loop.run_in_executor(None, sys.stdout.write, data)
        await loop.run_in_executor(None, sys.stdout.flush)
    elif target is not None:
        await loop.run_in_executor(None, Path(target).write_text, data, "utf-8")
