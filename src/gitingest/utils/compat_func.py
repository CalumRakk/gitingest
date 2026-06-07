"""Compatibility functions for Python 3.8."""

import os
from pathlib import Path


def readlink(path: Path) -> Path:
    """Read the target of a symlink.

    Compatible with Python 3.8.

    Parameters
    ----------
    path : Path
        Path to the symlink.

    Returns
    -------
    Path
        The target of the symlink.

    """
    return Path(os.readlink(path))
