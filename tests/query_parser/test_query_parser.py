"""Tests for the ``query_parser`` module."""

from __future__ import annotations

from pathlib import Path

import pytest

from gitingest.query_parser import parse_local_dir_path


def test_parse_local_dir_path_local_path() -> None:
    """Test ``parse_local_dir_path`` with absolute paths."""
    path = "/home/user/project"
    query = parse_local_dir_path(path)
    tail = Path("home/user/project")

    assert query.local_path.parts[-len(tail.parts) :] == tail.parts
    assert query.id is not None
    assert query.slug == "home/user/project"


def test_parse_local_dir_path_relative_path() -> None:
    """Test ``parse_local_dir_path`` with a relative path."""
    path = "./project"
    query = parse_local_dir_path(path)
    tail = Path("project")

    assert query.local_path.parts[-len(tail.parts) :] == tail.parts
    assert query.slug.endswith("project")


def test_parse_local_dir_path_uuid_uniqueness() -> None:
    """Test ``parse_local_dir_path`` for unique UUID generation."""
    path = "/home/user/project"
    query_1 = parse_local_dir_path(path)
    query_2 = parse_local_dir_path(path)

    assert query_1.id != query_2.id
