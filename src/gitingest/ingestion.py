"""Functions to ingest and analyze a codebase directory or single file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gitingest.config import MAX_DIRECTORY_DEPTH, MAX_FILES, MAX_TOTAL_SIZE_BYTES
from gitingest.output_formatter import format_node
from gitingest.schemas import FileSystemNode, FileSystemNodeType, FileSystemStats
from gitingest.utils.ignore_patterns import DEFAULT_IGNORE_PATTERNS  # Importación del set por defecto
from gitingest.utils.ingestion_utils import _should_exclude, _should_include
from gitingest.utils.logging_config import get_logger

if TYPE_CHECKING:
    from gitingest.schemas import IngestionQuery

# Initialize logger for this module
logger = get_logger(__name__)


def ingest_query(query: IngestionQuery) -> tuple[str, str, str]:
    logger.info(
        "Starting file ingestion",
        extra={
            "slug": query.slug,
            "max_file_size": query.max_file_size,
        },
    )

    # Consolidación de la fuente de verdad para exclusiones por defecto
    if query.ignore_patterns is None:
        query.ignore_patterns = DEFAULT_IGNORE_PATTERNS.copy()
    else:
        query.ignore_patterns.update(DEFAULT_IGNORE_PATTERNS)

    root_node = FileSystemNode(
        name=query.slug,
        type=FileSystemNodeType.DIRECTORY,
        path_str="",
        path=query.local_path,
    )
    stats = FileSystemStats()

    # Si no se definieron targets virtuales, creamos el target por defecto (backward compatibility)
    targets = query.targets
    if not targets:
        from gitingest.schemas.ingestion import VirtualTarget

        targets = [
            VirtualTarget(
                physical_path=query.local_path / Path(query.subpath.strip("/")),
                virtual_alias=".",
                is_file=query.local_path.is_file() or (query.type == "blob"),
            ),
        ]

    for target in targets:
        phys_path = target.physical_path
        if not phys_path.exists():
            logger.warning(f"La ruta del target no existe físicamente: {phys_path}")
            continue

        if target.is_file or phys_path.is_file():
            # Procesado de un archivo específico
            if target.virtual_alias and target.virtual_alias != ".":
                virtual_path_str = (Path(target.virtual_alias) / phys_path.name).as_posix()
            else:
                virtual_path_str = phys_path.name

            file_node = FileSystemNode(
                name=phys_path.name,
                type=FileSystemNodeType.FILE,
                size=phys_path.stat().st_size,
                file_count=1,
                path_str=virtual_path_str,
                path=phys_path,
            )

            if len(targets) == 1 and target.virtual_alias == ".":
                return format_node(file_node, query=query)
            root_node.children.append(file_node)
            root_node.size += file_node.size
            root_node.file_count += 1
        # Procesado de un directorio
        elif target.virtual_alias == ".":
            # Mezclar contenidos en la raíz del contexto unificado
            _process_node(
                node=root_node,
                query=query,
                stats=stats,
                base_path=phys_path,
                virtual_prefix=".",
            )
        else:
            # Encapsular bajo un nodo con el nombre del alias virtual
            dir_node = FileSystemNode(
                name=target.virtual_alias,
                type=FileSystemNodeType.DIRECTORY,
                path_str=target.virtual_alias,
                path=phys_path,
                depth=1,
            )
            _process_node(
                node=dir_node,
                query=query,
                stats=stats,
                base_path=phys_path,
                virtual_prefix=target.virtual_alias,
            )
            if dir_node.children:
                root_node.children.append(dir_node)
                root_node.size += dir_node.size
                root_node.file_count += dir_node.file_count
                root_node.dir_count += 1 + dir_node.dir_count

    root_node.sort_children()
    return format_node(root_node, query=query)


def _process_node(
    node: FileSystemNode,
    query: IngestionQuery,
    stats: FileSystemStats,
    base_path: Path,
    virtual_prefix: str,
) -> None:
    if limit_exceeded(stats, depth=node.depth):
        return

    for sub_path in node.path.iterdir():
        # Evaluamos ignores utilizando la ruta física base de este sub-árbol
        if query.ignore_patterns and _should_exclude(sub_path, base_path, query.ignore_patterns):
            continue

        if query.include_patterns and not _should_include(sub_path, base_path, query.include_patterns):
            continue

        # Construcción dinámica de la ruta virtual del archivo o carpeta
        rel_path = sub_path.relative_to(base_path)
        if virtual_prefix and virtual_prefix != ".":
            virtual_path_str = (Path(virtual_prefix) / rel_path).as_posix()
        else:
            virtual_path_str = rel_path.as_posix()

        if sub_path.is_symlink():
            child = FileSystemNode(
                name=sub_path.name,
                type=FileSystemNodeType.SYMLINK,
                path_str=virtual_path_str,
                path=sub_path,
                depth=node.depth + 1,
            )
            stats.total_files += 1
            node.children.append(child)
            node.file_count += 1

        elif sub_path.is_file():
            if sub_path.stat().st_size > query.max_file_size:
                continue

            if stats.total_files + 1 > MAX_FILES:
                return

            file_size = sub_path.stat().st_size
            if stats.total_size + file_size > MAX_TOTAL_SIZE_BYTES:
                return

            stats.total_files += 1
            stats.total_size += file_size

            child = FileSystemNode(
                name=sub_path.name,
                type=FileSystemNodeType.FILE,
                size=file_size,
                file_count=1,
                path_str=virtual_path_str,
                path=sub_path,
                depth=node.depth + 1,
            )
            node.children.append(child)
            node.size += file_size
            node.file_count += 1

        elif sub_path.is_dir():
            child_directory_node = FileSystemNode(
                name=sub_path.name,
                type=FileSystemNodeType.DIRECTORY,
                path_str=virtual_path_str,
                path=sub_path,
                depth=node.depth + 1,
            )

            _process_node(
                node=child_directory_node,
                query=query,
                stats=stats,
                base_path=base_path,
                virtual_prefix=virtual_prefix,
            )

            if not child_directory_node.children:
                continue

            node.children.append(child_directory_node)
            node.size += child_directory_node.size
            node.file_count += child_directory_node.file_count
            node.dir_count += 1 + child_directory_node.dir_count

    node.sort_children()


def limit_exceeded(stats: FileSystemStats, depth: int) -> bool:
    if depth > MAX_DIRECTORY_DEPTH:
        logger.warning(
            "Maximum directory depth limit reached",
            extra={"current_depth": depth, "max_depth": MAX_DIRECTORY_DEPTH},
        )
        return True

    if stats.total_files >= MAX_FILES:
        logger.warning(
            "Maximum file limit reached",
            extra={"current_files": stats.total_files, "max_files": MAX_FILES},
        )
        return True

    if stats.total_size >= MAX_TOTAL_SIZE_BYTES:
        logger.warning(
            "Maximum total size limit reached",
            extra={
                "current_size_mb": stats.total_size / 1024 / 1024,
                "max_size_mb": MAX_TOTAL_SIZE_BYTES / 1024 / 1024,
            },
        )
        return True

    return False
