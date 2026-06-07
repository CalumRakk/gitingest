"""Module containing functions to parse and validate local input sources."""

from __future__ import annotations

import uuid
from pathlib import Path

from gitingest.schemas import IngestionQuery


def parse_local_dir_path(path_str: str) -> IngestionQuery:
    """Parse the given file path into a structured query dictionary.

    Parameters
    ----------
    path_str : str
        The file path to parse.

    Returns
    -------
    IngestionQuery
        A dictionary containing the parsed details of the file path.
    """
    path_obj = Path(path_str).resolve()
    slug = path_obj.name if path_str == "." else path_str.strip("/")
    return IngestionQuery(local_path=path_obj, slug=slug, id=uuid.uuid4())
