"""Module containing the dataclasses for the local ingestion process."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from gitingest.config import MAX_FILE_SIZE


class IngestionQuery(BaseModel):
    """Pydantic model to store the parsed details of the local file path.

    Attributes
    ----------
    local_path : Path
        The local path to the repository or file.
    slug : str
        The slug of the repository.
    id : UUID
        The ID of the repository.
    subpath : str
        The subpath to the repository or file (default: "/").
    type : str | None
        The type of the repository or file.
    max_file_size : int
        The maximum file size to ingest in bytes (default: 10 MB).
    ignore_patterns : set[str]
        The patterns to ignore (default: ``set()``).
    include_patterns : set[str] | None
        The patterns to include.
    """

    local_path: Path
    slug: str
    id: UUID
    subpath: str = Field(default="/")
    type: str | None = None
    max_file_size: int = Field(default=MAX_FILE_SIZE)
    ignore_patterns: set[str] = Field(default_factory=set)
    include_patterns: set[str] | None = None
