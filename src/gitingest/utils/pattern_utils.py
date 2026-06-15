"""Pattern utilities for the Gitingest package."""

from __future__ import annotations

import re
from collections.abc import Iterable

from gitingest.utils.ignore_patterns import DEFAULT_IGNORE_PATTERNS

_PATTERN_SPLIT_RE = re.compile(r"[,\s]+")


def process_patterns(
    exclude_patterns: str | set[str] | None = None,
    include_patterns: str | set[str] | None = None,
) -> tuple[set[str], set[str] | None]:
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

    Soporta listas programáticas evitando fragmentar rutas legítimas con espacios.
    """
    if isinstance(patterns, str):
        patterns = [patterns]

    normalized_patterns = set()

    for pat in patterns:
        if not pat or not isinstance(pat, str):
            continue

        # Si el patrón contiene comas, asumimos delimitación múltiple.
        # Si no, lo tratamos como una única regla directa preservando los espacios.
        if "," in pat:
            parts = [p.strip() for p in pat.split(",") if p.strip()]
        else:
            parts = [pat.strip()]

        for part in parts:
            normalized_patterns.add(part.replace("\\", "/"))

    return normalized_patterns
