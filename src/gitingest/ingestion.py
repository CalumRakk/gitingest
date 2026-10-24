"""Functions to ingest and analyze a codebase directory or single file."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pathspec import PathSpec
from utils.ingestion_utils import _relative_or_none

from gitingest.config import MAX_DIRECTORY_DEPTH, MAX_FILES, MAX_TOTAL_SIZE_BYTES
from gitingest.output_formatter import format_node
from gitingest.schemas import FileSystemNode, FileSystemNodeType, FileSystemStats
from gitingest.utils.ignore_patterns import DEFAULT_IGNORE_PATTERNS
from gitingest.utils.ingestion_utils import _should_exclude, _should_include
from gitingest.utils.logging_config import get_logger

if TYPE_CHECKING:
    from gitingest.schemas import IngestionQuery


diag_logger = logging.getLogger("project_context.gitingest")
# Initialize logger for this module
logger = get_logger(__name__)

MAX_EXCLUDED_PREVIEW = 20
JUNK_IGNORE_PATTERNS = {".ds_store", "thumbs.db", "desktop.ini", "__pycache__", ".git", ".pytest_cache"}


def _matches_exclusion_rule(path: Path, base_path: Path, spec: PathSpec | None) -> bool:
    """Checks whether a path or directory matches the context exclude rules."""
    if not spec:
        return False
    if _should_exclude(path, base_path, spec):
        return True

    if path.is_dir():
        rel = _relative_or_none(path, base_path)
        if rel:
            return spec.match_file((rel / "dummy_file").as_posix())
    return False


def _process_excluded_directory(
    dir_node: FileSystemNode,
    base_path: Path,
    virtual_prefix: str,
    stats: FileSystemStats,
    max_preview: int = MAX_EXCLUDED_PREVIEW,
) -> None:
    """Safely and lazily traverse the files within an excluded folder."""
    count = 0
    has_more = False

    try:
        for child_path in dir_node.path.iterdir():
            if child_path.name.lower() in JUNK_IGNORE_PATTERNS or child_path.name.endswith(".pyc"):
                continue

            if count >= max_preview:
                has_more = True
                break

            rel_path = child_path.relative_to(base_path)
            virtual_path_str = (
                (Path(virtual_prefix) / rel_path).as_posix()
                if virtual_prefix and virtual_prefix != "."
                else rel_path.as_posix()
            )

            if child_path.is_symlink():
                child_node = FileSystemNode(
                    name=child_path.name,
                    type=FileSystemNodeType.SYMLINK,
                    path_str=virtual_path_str,
                    path=child_path,
                    depth=dir_node.depth + 1,
                    is_excluded=True,
                    suppress_content=True,
                )
                dir_node.children.append(child_node)
                dir_node.file_count += 1
                stats.total_files += 1
                count += 1

            elif child_path.is_file():
                child_node = FileSystemNode(
                    name=child_path.name,
                    type=FileSystemNodeType.FILE,
                    size=0,
                    file_count=1,
                    path_str=virtual_path_str,
                    path=child_path,
                    depth=dir_node.depth + 1,
                    is_excluded=True,
                    suppress_content=True,
                )
                dir_node.children.append(child_node)
                dir_node.file_count += 1
                stats.total_files += 1
                count += 1

            elif child_path.is_dir():
                sub_dir_node = FileSystemNode(
                    name=child_path.name,
                    type=FileSystemNodeType.DIRECTORY,
                    path_str=virtual_path_str,
                    path=child_path,
                    depth=dir_node.depth + 1,
                    is_excluded=True,
                )
                dir_node.children.append(sub_dir_node)
                dir_node.dir_count += 1
                count += 1

    except (OSError, PermissionError) as e:
        logger.debug("Could not read excluded folder {dir_node.path}: {e}")

    if has_more:
        ellipsis_node = FileSystemNode(
            name="... (más elementos omitidos)",
            type=FileSystemNodeType.FILE,
            path_str=f"{dir_node.path_str}/...",
            path=dir_node.path,
            depth=dir_node.depth + 1,
            is_excluded=False,
            suppress_content=True,
            is_ellipsis=True,
        )
        dir_node.children.append(ellipsis_node)

    dir_node.sort_children()


def _has_whitelisted_descendant(dir_path: Path, whitelisted_paths: set[Path]) -> bool:
    """Verifica si algún archivo forzado (whitelist) es descendiente de este directorio."""
    resolved_dir = dir_path.resolve()
    for wp in whitelisted_paths:
        try:
            if resolved_dir in wp.parents or resolved_dir == wp:
                return True
        except Exception:
            pass
    return False


def _insert_node_hierarchically(
    root_node: FileSystemNode,
    file_node: FileSystemNode,
    rel_path: Path,
    base_physical_dir: Path,
) -> None:
    """Inserta un FileSystemNode en su ruta jerárquica real, creando carpetas intermedias si faltan."""
    parts = rel_path.parts  # ej: ("src", "services", "auth.py")
    current_node = root_node
    accumulated_path = Path()

    for part in parts[:-1]:
        accumulated_path = accumulated_path / part
        current_virtual_str = (
            f"{root_node.path_str}/{accumulated_path.as_posix()}".strip("/")
            if root_node.path_str and root_node.path_str != "."
            else accumulated_path.as_posix()
        )

        matching_dir = next(
            (c for c in current_node.children if c.type == FileSystemNodeType.DIRECTORY and c.name == part),
            None,
        )

        if not matching_dir:
            matching_dir = FileSystemNode(
                name=part,
                type=FileSystemNodeType.DIRECTORY,
                path_str=current_virtual_str,
                path=base_physical_dir / accumulated_path,
                depth=current_node.depth + 1,
            )
            current_node.children.append(matching_dir)
            current_node.dir_count += 1

        current_node = matching_dir

    # Insertar el archivo en la carpeta contenedora final
    file_node.depth = current_node.depth + 1
    existing_idx = next(
        (i for i, c in enumerate(current_node.children) if c.name == file_node.name),
        None,
    )
    if existing_idx is not None:
        current_node.children[existing_idx] = file_node
    else:
        current_node.children.append(file_node)
        current_node.file_count += 1
        current_node.size += file_node.size


def ingest_query(query: IngestionQuery) -> tuple[str, str, str]:
    diag_logger.info(f"[GITINGEST] Iniciando ingestión para: {query.local_path}")
    t_start = time.perf_counter()

    if query.ignore_patterns is None:
        query.ignore_patterns = DEFAULT_IGNORE_PATTERNS.copy()
    else:
        query.ignore_patterns.update(DEFAULT_IGNORE_PATTERNS)

    ignore_spec = PathSpec.from_lines("gitwildmatch", query.ignore_patterns) if query.ignore_patterns else None
    exclude_spec = PathSpec.from_lines("gitwildmatch", query.exclude_patterns) if query.exclude_patterns else None
    include_spec = PathSpec.from_lines("gitwildmatch", query.include_patterns) if query.include_patterns else None

    root_node = FileSystemNode(
        name=query.slug,
        type=FileSystemNodeType.DIRECTORY,
        path_str="",
        path=query.local_path,
    )
    stats = FileSystemStats()

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
    whitelisted_files = {t.physical_path.resolve() for t in targets if t.is_file}

    for target in targets:
        phys_path = target.physical_path
        if not phys_path.exists() or target.is_file or phys_path.is_file():
            continue

        diag_logger.info(f"[GITINGEST] Procesando target directorio: '{target.virtual_alias}' ({phys_path})")
        t_target = time.perf_counter()

        if target.virtual_alias == ".":
            _process_node(
                node=root_node,
                query=query,
                stats=stats,
                base_path=phys_path,
                virtual_prefix=".",
                ignore_spec=ignore_spec,
                exclude_spec=exclude_spec,
                include_spec=include_spec,
                whitelisted_files=whitelisted_files,
            )
        else:
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
                ignore_spec=ignore_spec,
                exclude_spec=exclude_spec,
                include_spec=include_spec,
                whitelisted_files=whitelisted_files,
            )
            if dir_node.children:
                root_node.children.append(dir_node)
                root_node.size += dir_node.size
                root_node.file_count += dir_node.file_count
                root_node.dir_count += 1 + dir_node.dir_count

        diag_logger.info(
            f"[GITINGEST] Target '{target.virtual_alias}' escaneado en {time.perf_counter() - t_target:.3f}s. "
            f"Archivos encontrados hasta ahora: {stats.total_files}"
        )

    for target in targets:
        phys_path = target.physical_path
        if not phys_path.exists():
            continue
        if not target.is_file and not phys_path.is_file():
            continue

        is_external = target.virtual_alias and target.virtual_alias != "."

        if is_external:
            base_dir = phys_path.parent
            rel_file_path = Path(phys_path.name)
            virtual_path_str = f"{target.virtual_alias}/{phys_path.name}"
        else:
            try:
                rel_file_path = phys_path.resolve().relative_to(query.local_path.resolve())
            except ValueError:
                rel_file_path = Path(phys_path.name)
            base_dir = query.local_path
            virtual_path_str = rel_file_path.as_posix()

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

        if is_external:
            matching_ext_dir = next(
                (
                    c
                    for c in root_node.children
                    if c.type == FileSystemNodeType.DIRECTORY and c.name == target.virtual_alias
                ),
                None,
            )
            if not matching_ext_dir:
                matching_ext_dir = FileSystemNode(
                    name=target.virtual_alias,
                    type=FileSystemNodeType.DIRECTORY,
                    path_str=target.virtual_alias,
                    path=phys_path.parent,
                    depth=1,
                )
                root_node.children.append(matching_ext_dir)
                root_node.dir_count += 1

            _insert_node_hierarchically(matching_ext_dir, file_node, rel_file_path, base_dir)
        else:
            _insert_node_hierarchically(root_node, file_node, rel_file_path, base_dir)

    root_node.sort_children()
    diag_logger.info(
        f"[GITINGEST] Escaneo de disco finalizado en {time.perf_counter() - t_start:.3f}s. "
        f"Total archivos válidos: {stats.total_files} ({stats.total_size / 1024 / 1024:.2f} MB). "
        f"Iniciando format_node()..."
    )
    return format_node(root_node, query=query)


def _process_node(
    node: FileSystemNode,
    query: IngestionQuery,
    stats: FileSystemStats,
    base_path: Path,
    virtual_prefix: str,
    ignore_spec: PathSpec | None = None,
    exclude_spec: PathSpec | None = None,
    include_spec: PathSpec | None = None,
    whitelisted_files: set[Path] | None = None,
) -> None:
    if limit_exceeded(stats, depth=node.depth):
        return

    whitelisted_set = whitelisted_files or set()

    for sub_path in node.path.iterdir():
        is_whitelisted = sub_path.resolve() in whitelisted_set
        has_whitelisted_child = sub_path.is_dir() and _has_whitelisted_descendant(sub_path, whitelisted_set)

        is_soft_excluded = False
        if not is_whitelisted:
            if _matches_exclusion_rule(sub_path, base_path, exclude_spec):
                is_soft_excluded = True

        if not is_whitelisted and not has_whitelisted_child and not is_soft_excluded:
            if ignore_spec and _should_exclude(sub_path, base_path, ignore_spec):
                continue

        if include_spec and not _should_include(sub_path, base_path, include_spec):
            continue

        rel_path = sub_path.relative_to(base_path)
        virtual_path_str = (
            (Path(virtual_prefix) / rel_path).as_posix()
            if virtual_prefix and virtual_prefix != "."
            else rel_path.as_posix()
        )

        if sub_path.is_symlink():
            child = FileSystemNode(
                name=sub_path.name,
                type=FileSystemNodeType.SYMLINK,
                path_str=virtual_path_str,
                path=sub_path,
                depth=node.depth + 1,
                is_excluded=is_soft_excluded,
                suppress_content=is_soft_excluded,
            )
            stats.total_files += 1
            node.children.append(child)
            node.file_count += 1

        elif sub_path.is_file():
            if is_soft_excluded:
                child = FileSystemNode(
                    name=sub_path.name,
                    type=FileSystemNodeType.FILE,
                    size=0,
                    file_count=1,
                    path_str=virtual_path_str,
                    path=sub_path,
                    depth=node.depth + 1,
                    is_excluded=True,
                    suppress_content=True,
                )
                node.children.append(child)
                node.file_count += 1
                continue

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
            if is_soft_excluded and not has_whitelisted_child:
                child_directory_node = FileSystemNode(
                    name=sub_path.name,
                    type=FileSystemNodeType.DIRECTORY,
                    path_str=virtual_path_str,
                    path=sub_path,
                    depth=node.depth + 1,
                    is_excluded=True,
                )

                _process_excluded_directory(
                    dir_node=child_directory_node,
                    base_path=base_path,
                    virtual_prefix=virtual_prefix,
                    stats=stats,
                    max_preview=MAX_EXCLUDED_PREVIEW,
                )
                node.children.append(child_directory_node)
                node.dir_count += 1
                continue

            child_directory_node = FileSystemNode(
                name=sub_path.name,
                type=FileSystemNodeType.DIRECTORY,
                path_str=virtual_path_str,
                path=sub_path,
                depth=node.depth + 1,
                is_partially_excluded=is_soft_excluded,
            )

            _process_node(
                node=child_directory_node,
                query=query,
                stats=stats,
                base_path=base_path,
                virtual_prefix=virtual_prefix,
                ignore_spec=ignore_spec,
                exclude_spec=exclude_spec,
                include_spec=include_spec,
                whitelisted_files=whitelisted_set,
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
