"""Utility functions for the ingestion process."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pathspec import PathSpec

if TYPE_CHECKING:
    from pathlib import Path


def _should_include(path: Path, base_path: Path, spec: PathSpec) -> bool:
    """Return ``True`` if ``path`` matches the include specification."""
    rel_path = _relative_or_none(path, base_path)
    if rel_path is None:
        return False
    if path.is_dir():
        return True

    rel_path_str = rel_path.as_posix()
    return spec.match_file(rel_path_str)


def _should_exclude(path: Path, base_path: Path, spec: PathSpec) -> bool:
    """Return ``True`` if ``path`` matches the ignore specification."""
    rel_path = _relative_or_none(path, base_path)
    if rel_path is None:
        return True

    rel_path_str = rel_path.as_posix()
    if path.is_dir():
        rel_path_str += "/"

    return spec.match_file(rel_path_str)


def _relative_or_none(path: Path, base: Path) -> Path | None:
    """Return *path* relative to *base* or ``None`` if *path* is outside *base*.

    Parameters
    ----------
    path : Path
        The absolute path of the file or directory to check.
    base : Path
        The base directory from which the relative path is calculated.

    Returns
    -------
    Path | None
        The relative path of ``path`` to ``base``, or ``None`` if ``path`` is outside ``base``.

    """
    try:
        return path.relative_to(base)
    except ValueError:  # path is not a sub-path of base
        return None
