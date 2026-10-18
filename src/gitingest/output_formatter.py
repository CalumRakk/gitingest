"""Functions to ingest and analyze a codebase directory or single file."""

from __future__ import annotations

import logging
import ssl
import time
from typing import TYPE_CHECKING

import requests.exceptions
import tiktoken

from gitingest.schemas import FileSystemNode, FileSystemNodeType
from gitingest.utils.compat_func import readlink
from gitingest.utils.logging_config import get_logger

if TYPE_CHECKING:
    from gitingest.schemas import IngestionQuery


diag_logger = logging.getLogger("project_context.formatter")
# Initialize logger for this module
logger = get_logger(__name__)

_TOKEN_THRESHOLDS: list[tuple[int, str]] = [
    (1_000_000, "M"),
    (1_000, "k"),
]


def format_node(node: FileSystemNode, query: IngestionQuery) -> tuple[str, str, str]:
    """Generate a summary, directory structure, and file contents for a given file system node.

    If the node represents a directory, the function will recursively process its contents.

    Parameters
    ----------
    node : FileSystemNode
        The file system node to be summarized.
    query : IngestionQuery
        The parsed query object containing information about the repository and query parameters.

    Returns
    -------
    tuple[str, str, str]
        A tuple containing the summary, directory structure, and file contents.

    """
    t_start = time.perf_counter()
    diag_logger.info("[FORMATTER 1/4] format_node() iniciado")

    is_single_file = node.type == FileSystemNodeType.FILE
    summary = _create_summary_prefix(query, single_file=is_single_file)

    t_gather = time.perf_counter()
    diag_logger.info("[FORMATTER 2/4] Leyendo contenido de archivos desde disco (_gather_file_contents)...")
    content = _gather_file_contents(node)
    diag_logger.info(
        f"[FORMATTER 2/4] Lectura de archivos lista en {time.perf_counter() - t_gather:.3f}s. "
        f"Tamaño texto: {len(content):,} caracteres"
    )

    if node.type == FileSystemNodeType.DIRECTORY:
        summary += f"Files analyzed: {node.file_count}\n"
    elif node.type == FileSystemNodeType.FILE:
        summary += f"File: {node.name}\n"
        summary += f"Lines: {len(node.content.splitlines()):,}\n"

    t_tree = time.perf_counter()
    tree = "Directory structure:\n" + _create_tree_structure(query, node=node)
    diag_logger.info(f"[FORMATTER 3/4] Árbol de directorios creado en {time.perf_counter() - t_tree:.3f}s")

    t_tok = time.perf_counter()
    diag_logger.info("[FORMATTER 4/4] Estimando tokens con tiktoken (_format_token_count)...")
    token_estimate = _format_token_count(tree + content)
    diag_logger.info(
        f"[FORMATTER 4/4] Estimación de tokens lista en {time.perf_counter() - t_tok:.3f}s. "
        f"Resultado: {token_estimate}"
    )

    if token_estimate:
        summary += f"\nEstimated tokens: {token_estimate}"

    diag_logger.info(f"[FORMATTER] format_node() completado en {time.perf_counter() - t_start:.3f}s")
    return summary, tree, content


def _create_summary_prefix(query: IngestionQuery, *, single_file: bool = False) -> str:
    """Create a prefix string for summarizing a repository or local directory.

    Includes repository name (if provided), commit/branch details, and subpath if relevant.

    Parameters
    ----------
    query : IngestionQuery
        The parsed query object containing information about the repository and query parameters.
    single_file : bool
        A flag indicating whether the summary is for a single file (default: ``False``).

    Returns
    -------
    str
        A summary prefix string containing repository, commit, branch, and subpath details.

    """
    parts = []

    if query.user_name:
        parts.append(f"Repository: {query.user_name}/{query.repo_name}")
    else:
        # Local scenario
        parts.append(f"Directory: {query.slug}")

    if query.tag:
        parts.append(f"Tag: {query.tag}")
    elif query.branch and query.branch not in ("main", "master"):
        parts.append(f"Branch: {query.branch}")

    if query.commit:
        parts.append(f"Commit: {query.commit}")

    if query.subpath != "/" and not single_file:
        parts.append(f"Subpath: {query.subpath}")

    return "\n".join(parts) + "\n"


def _gather_file_contents(node: FileSystemNode) -> str:
    """Recursively gather contents of all files under the given node.

    This function recursively processes a directory node and gathers the contents of all files
    under that node. It returns the concatenated content of all files as a single string.

    Parameters
    ----------
    node : FileSystemNode
        The current directory or file node being processed.

    Returns
    -------
    str
        The concatenated content of all files under the given node.

    """
    if node.type != FileSystemNodeType.DIRECTORY:
        return node.content_string

    # Recursively gather contents of all files under the current directory
    return "\n".join(_gather_file_contents(child) for child in node.children)


def _create_tree_structure(
    query: IngestionQuery,
    *,
    node: FileSystemNode,
    prefix: str = "",
    is_last: bool = True,
) -> str:
    """Generate a tree-like string representation of the file structure.

    This function generates a string representation of the directory structure, formatted
    as a tree with appropriate indentation for nested directories and files.

    Parameters
    ----------
    query : IngestionQuery
        The parsed query object containing information about the repository and query parameters.
    node : FileSystemNode
        The current directory or file node being processed.
    prefix : str
        A string used for indentation and formatting of the tree structure (default: ``""``).
    is_last : bool
        A flag indicating whether the current node is the last in its directory (default: ``True``).

    Returns
    -------
    str
        A string representing the directory structure formatted as a tree.

    """
    if not node.name:
        node.name = query.slug

    tree_str = ""
    current_prefix = "└── " if is_last else "├── "

    display_name = node.name
    if node.type == FileSystemNodeType.DIRECTORY:
        display_name += "/"
        if getattr(node, "is_excluded", False):
            display_name += " (excluido)"
        elif getattr(node, "is_partially_excluded", False):
            display_name += " (resto excluido)"
    elif node.type == FileSystemNodeType.SYMLINK:
        display_name += " -> " + readlink(node.path).name
    elif getattr(node, "is_partial", False):
        display_name += " (parcial)"
    elif getattr(node, "is_excluded", False):
        display_name += " (excluido)"

    tree_str += f"{prefix}{current_prefix}{display_name}\n"

    if node.type == FileSystemNodeType.DIRECTORY and node.children:
        prefix += "    " if is_last else "│   "
        for i, child in enumerate(node.children):
            tree_str += _create_tree_structure(query, node=child, prefix=prefix, is_last=i == len(node.children) - 1)
    return tree_str


def _format_token_count(text: str) -> str | None:
    """Return a human-readable token-count string (e.g. 1.2k, 1.2 M).

    Parameters
    ----------
    text : str
        The text string for which the token count is to be estimated.

    Returns
    -------
    str | None
        The formatted number of tokens as a string (e.g., ``"1.2k"``, ``"1.2M"``), or ``None`` if an error occurs.

    """
    try:
        t_bpe = time.perf_counter()
        diag_logger.debug("[TIKTOKEN] Obteniendo encoding 'o200k_base'...")
        encoding = tiktoken.get_encoding("o200k_base")  # gpt-4o, gpt-4o-mini
        diag_logger.debug(f"[TIKTOKEN] get_encoding listo en {time.perf_counter() - t_bpe:.3f}s")

        t_enc = time.perf_counter()
        diag_logger.debug(f"[TIKTOKEN] Ejecutando encode() en {len(text):,} caracteres...")
        total_tokens = len(encoding.encode(text, disallowed_special=()))
        diag_logger.debug(f"[TIKTOKEN] encode() listo en {time.perf_counter() - t_enc:.3f}s ({total_tokens:,} tokens)")
    except (ValueError, UnicodeEncodeError) as exc:
        logger.warning("Failed to estimate token size", extra={"error": str(exc)})
        return None
    except (requests.exceptions.RequestException, ssl.SSLError) as exc:
        logger.warning("Failed to download tiktoken model", extra={"error": str(exc)})
        return None

    for threshold, suffix in _TOKEN_THRESHOLDS:
        if total_tokens >= threshold:
            return f"{total_tokens / threshold:.1f}{suffix}"

    return str(total_tokens)
