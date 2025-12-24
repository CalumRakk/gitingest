"""Pattern utilities for the Gitingest package."""

from __future__ import annotations

import re
import shlex
from typing import Iterable

from gitingest.utils.ignore_patterns import DEFAULT_IGNORE_PATTERNS

_PATTERN_SPLIT_RE = re.compile(r"[,\s]+")


def process_patterns(
    exclude_patterns: str | set[str] | None = None,
    include_patterns: str | set[str] | None = None,
) -> tuple[set[str], set[str] | None]:
    """Process include and exclude patterns.

    Parameters
    ----------
    exclude_patterns : str | set[str] | None
        Exclude patterns to process.
    include_patterns : str | set[str] | None
        Include patterns to process.

    Returns
    -------
    tuple[set[str], set[str] | None]
        A tuple containing the processed ignore patterns and include patterns.

    """
    # Combine default ignore patterns + custom patterns
    ignore_patterns_set = DEFAULT_IGNORE_PATTERNS.copy()
    if exclude_patterns:
        ignore_patterns_set.update(_parse_patterns(exclude_patterns))

    # Process include patterns and override ignore patterns accordingly
    if include_patterns:
        parsed_include = _parse_patterns(include_patterns)
        # Override ignore patterns with include patterns
        ignore_patterns_set = set(ignore_patterns_set) - set(parsed_include)
    else:
        parsed_include = None

    return ignore_patterns_set, parsed_include


def _parse_patterns(patterns: str | Iterable[str]) -> set[str]:
    """Normalize a collection of file or directory patterns.

    Processes strings or iterables, supporting comma and whitespace as delimiters.
    Uses a shell-like parser to respect quotes, allowing spaces and commas
    within filenames (e.g., '"file, with space.txt"').

    Parameters
    ----------
    patterns : str | Iterable[str]
        One or more pattern strings. Patterns can be separated by commas or
        spaces. Use quotes for patterns containing spaces.

    Returns
    -------
    set[str]
        A set of normalized patterns with backslashes converted to forward
        slashes and duplicates removed.

    Examples
    --------
    >>> _parse_patterns('*.py, "folder name/*"')
    {'*.py', 'folder name/*'}

    """
    # Treat a lone string as the iterable [string]
    if isinstance(patterns, str):
        patterns = [patterns]

    normalized_patterns = set()

    for pat in patterns:
        if not pat or not isinstance(pat, str):
            continue

        comma_parts = pat.split(",")
        for p in comma_parts:
            stripped_part = p.strip()
            if not stripped_part:
                continue

            try:
                # posix=True It removes external quotes and handles escapes.
                sub_parts = shlex.split(stripped_part, posix=True)
            except ValueError:
                sub_parts = _PATTERN_SPLIT_RE.split(stripped_part)

            for sp in sub_parts:
                if sp:
                    normalized_patterns.add(sp.replace("\\", "/"))

    return normalized_patterns
