r"""
Structure file persistence, change resolution, and output management.

Save directory structure files, detect changes between versions, and
manage output directories. All functions operate on explicit parameters
or on a ``PersistenceContext`` value object rather than requiring access
to the ``DirectoryStructure`` instance.

Log formatting and writing are handled by the caller (``main()``),
keeping this module free of presentation-layer dependencies.

Classes
-------
PersistenceContext : Immutable snapshot of the data needed by the persistence layer.
SaveResult : Result of saving a directory structure.
WriteStatus : Outcome of a structure file write operation.

Functions
---------
save_structure : Save a directory structure to a text file with change tracking.
prepare_tree_content : Format the project name and tree text into saveable content.

Examples
--------
>>> prepare_tree_content("demo", "├── main.py\n")
'demo/\n├── main.py\n'

"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Optional

from trellis.config import FilterSettings
from trellis.core.io import atomic_write_text
from trellis.tracking.comparator import StructureChanges
from trellis.tracking.detector import append_tr_meta

_log = logging.getLogger(__name__)


# ====================================== #
#              DATA TYPES                #
# ====================================== #


class WriteStatus(Enum):
    """
    Outcome of a structure file write operation.

    Attributes
    ----------
    SUCCESS
        File was written successfully (atomic or direct).
    DIR_CREATE_FAILED
        Unable to create output directory.
    WRITE_FAILED
        Unable to write file after atomic and direct attempts.

    """

    SUCCESS = "success"
    DIR_CREATE_FAILED = "dir_create_failed"
    WRITE_FAILED = "write_failed"


class PersistenceContext(NamedTuple):
    """
    Immutable snapshot of the data needed by the persistence layer.

    Bundles the ``DirectoryStructure`` attributes consumed by
    persistence functions into a single value object so that
    persistence logic is decoupled from the scanner class.

    Collection fields use immutable types where possible (``frozenset``
    for path sets, ``tuple`` for ancestry chains). The ``path_hierarchy``
    dict has immutable tuple values but a mutable container.

    Attributes
    ----------
    project_name : str
        Name of the project (derived from the root directory name).
    root_dir : str
        Path to the root directory being scanned.
    structure : str
        The generated text representation of the directory structure.
    scanned_paths : frozenset[str]
        Paths collected during the directory scan.
    path_hierarchy : dict[str, tuple[str, ...]]
        Ancestry mapping for each scanned path.
    filter_settings : FilterSettings
        Immutable snapshot of filtering-related configuration.
    tr_meta : str
        Compact metadata string captured at construction time.

    """

    project_name: str
    root_dir: str
    structure: str
    scanned_paths: frozenset[str]
    path_hierarchy: dict[str, tuple[str, ...]]
    filter_settings: FilterSettings
    tr_meta: str


# ====================================== #
#              SAVE LOGIC                #
# ====================================== #


class SaveResult(NamedTuple):
    """
    Result of saving a directory structure.

    Attributes
    ----------
    output_path : str
        Path to the saved structure file.
    changes : StructureChanges or None
        Categorized structural changes, or None if change detection
        was skipped (first run, read error, or config suppression).
    logs_dir : str
        Path to the logs directory, or empty string if not applicable.
    write_status : WriteStatus
        Outcome of the file write operation.
    read_error : str
        Description of a read error when loading the previous structure
        file, or empty string if no error occurred.

    """

    output_path: str
    changes: Optional[StructureChanges]
    logs_dir: str
    write_status: WriteStatus = WriteStatus.SUCCESS
    read_error: str = ""


def save_structure(ctx: PersistenceContext) -> SaveResult:
    """
    Save a directory structure to a text file with change tracking.

    Detects changes between the existing and new structure files, writes
    the new structure file, and returns the result. Log formatting and
    writing are the caller's responsibility.

    Parameters
    ----------
    ctx : PersistenceContext
        Snapshot of scanner state needed for persistence.

    Returns
    -------
    SaveResult
        Result containing output path, categorized changes, and logs dir.

    """
    # Create output directories (docs and optional logs)
    docs_dir, logs_dir = _ensure_output_directories(
        ctx.root_dir,
        ctx.filter_settings.output_dir,
        ctx.filter_settings.log_dir,
        ctx.filter_settings.log_structure_changes,
    )
    # Bail out when the output directory could not be created
    if not docs_dir:
        return SaveResult("", None, "", WriteStatus.DIR_CREATE_FAILED)

    # Build output path and prepare new content with metadata
    output_path = _build_output_path(docs_dir, ctx.project_name)
    tree_content = prepare_tree_content(ctx.project_name, ctx.structure)
    meta = ctx.tr_meta
    new_content = append_tr_meta(tree_content, meta)

    # First run: no existing file; write new content and return early
    if not Path(output_path).exists():
        write_status = _write_structure_file(output_path, new_content)
        return SaveResult(output_path, None, logs_dir, write_status)

    # Load previous file for change detection
    read_error = ""
    try:
        with Path(output_path).open(encoding="utf-8") as file:
            old_content = file.read()
    except (PermissionError, UnicodeDecodeError) as previous_file_read_error:
        # Record read error and regenerate without change detection
        read_error = f"{type(previous_file_read_error).__name__}: {previous_file_read_error}"
        write_status = _write_structure_file(output_path, new_content)
        return SaveResult(output_path, None, "", write_status, read_error)

    # Detect changes between old and new structure files
    structure_changes = _resolve_with_elements(
        tree_content,
        old_content,
        ctx.filter_settings,
        ctx.scanned_paths,
        ctx.path_hierarchy,
        ctx.project_name,
        meta,
    )

    # Write the new structure file
    write_status = _write_structure_file(output_path, new_content)

    return SaveResult(output_path, structure_changes, logs_dir, write_status)


def _resolve_with_elements(
    tree_content: str,
    old_content: str,
    filter_settings: FilterSettings,
    scanned_paths: frozenset[str],
    path_hierarchy: dict[str, tuple[str, ...]],
    project_name: str,
    meta: str,
) -> Optional[StructureChanges]:
    """
    Resolve path-level and element-level changes together.

    Parameters
    ----------
    tree_content : str
        The new tree-only content (without tr_meta).
    old_content : str
        Previous structure file content.
    filter_settings : FilterSettings
        Immutable snapshot of filtering-related configuration.
    scanned_paths : frozenset[str]
        Paths collected during the directory scan.
    path_hierarchy : dict[str, tuple[str, ...]]
        Ancestry mapping for each scanned path.
    project_name : str
        Name of the project.
    meta : str
        Current tr_meta string.

    Returns
    -------
    StructureChanges or None
        Element-level changes, path-only changes when the old file
        was malformed, or None if suppressed by config.

    """
    from trellis.core.filters import is_path_in_ignored_hierarchy
    from trellis.tracking.comparator import compare_structure_elements
    from trellis.tracking.detector import (
        analyze_structure_elements,
        detect_structure_changes,
        split_tree_and_meta,
    )

    settings = filter_settings
    # Split the old content into tree and metadata to check for pure config changes
    old_tree_content, old_meta_value, old_meta_status = split_tree_and_meta(
        old_content, project_name
    )

    # Skip change detection when only metadata changed and tree content is identical
    is_config_only_change = (
        old_meta_status == "valid"
        and old_meta_value != meta
        and old_tree_content == tree_content
        and not settings.log_config_only_changes
    )
    # Return early when changes are limited to configuration metadata
    if is_config_only_change:
        return None

    # Define path filter to skip ignored paths during change detection
    def _path_filter(path: str, ancestry: Sequence[str]) -> bool:
        return is_path_in_ignored_hierarchy(path, ancestry, settings)

    # Collect scanned paths and ancestry mapping for change detection
    collected = (scanned_paths, path_hierarchy)

    # Detect path-level changes (added/deleted paths)
    added_paths, deleted_paths, _ = detect_structure_changes(
        tree_content,
        old_content,
        project_name,
        _path_filter,
        settings,
        collected,
        old_tree_content=old_tree_content,
    )

    # Return path-level changes only when old file was malformed (root line not found); skip element
    # comparison to avoid noisy false positives from an empty old element map.
    if not old_tree_content:
        return compare_structure_elements({}, {}, added_paths, deleted_paths)

    # Detect element-level changes (added/removed functions, classes, etc.)
    old_elements = analyze_structure_elements(old_tree_content)
    new_elements = analyze_structure_elements(tree_content)
    return compare_structure_elements(old_elements, new_elements, added_paths, deleted_paths)


def prepare_tree_content(project_name: str, structure: str) -> str:
    """
    Format the project name and tree text into saveable content.

    Parameters
    ----------
    project_name : str
        Name of the project.
    structure : str
        The generated text representation of the directory structure.

    Returns
    -------
    str
        The project structure as a single string with root name and tree content.

    """
    return f"{project_name}/\n{structure.strip()}\n"


# ====================================== #
#           FILE OPERATIONS              #
# ====================================== #


def _sanitize_filename(name: str) -> str:
    """
    Remove filesystem-unsafe characters from a filename component.

    Parameters
    ----------
    name : str
        Raw name to sanitize.

    Returns
    -------
    str
        Sanitized name with path separators and control characters removed.

    """
    # Strip path separators and null bytes to prevent directory traversal
    return name.replace("/", "").replace("\\", "").replace("\0", "")


def _build_output_path(docs_dir: str, project_name: str) -> str:
    """
    Build the output file path for the structure file.

    Parameters
    ----------
    docs_dir : str
        Directory where the structure file will be saved.
    project_name : str
        Name of the project.

    Returns
    -------
    str
        Full path to the output file.

    """
    safe_name = _sanitize_filename(project_name)
    return str(Path(docs_dir) / f"{safe_name}_structure.txt")


def _write_structure_file(output_path: str, content: str) -> WriteStatus:
    """
    Write the structure content to the output file.

    Delegates to ``atomic_write_text`` for atomic write with retry
    and direct-write fallback.

    Parameters
    ----------
    output_path : str
        Path where the structure file will be saved.
    content : str
        Structure content to be written to the file.

    Returns
    -------
    WriteStatus
        Outcome of the write operation.

    """
    # Return SUCCESS when atomic write (or its fallback) succeeds
    if atomic_write_text(output_path, content):
        return WriteStatus.SUCCESS
    return WriteStatus.WRITE_FAILED


def _ensure_output_directories(
    root_dir: str, output_dir: str, log_dir: str, log_structure_changes: bool
) -> tuple[str, str]:
    """
    Create necessary output directories if they don't exist.

    Parameters
    ----------
    root_dir : str
        Path to the project root directory.
    output_dir : str
        Relative path for the output directory (e.g. ``"docs"``).
    log_dir : str
        Relative path for the log directory (e.g. ``"logs/trellis"``).
    log_structure_changes : bool
        Whether structure change logging is enabled. When False the
        logs directory is not created.

    Returns
    -------
    tuple[str, str]
        A tuple containing (output_directory_path, logs_directory_path).
        If the docs directory cannot be created, returns ``("", "")``.
        If the logs directory cannot be created or logging is disabled,
        ``logs_directory_path`` is ``""`` (graceful degradation).

    """
    resolved_root = Path(root_dir).resolve()

    # Create the main output directory for structure files
    docs_path = resolved_root / output_dir
    # Reject paths that escape the project root via traversal sequences
    if not docs_path.resolve().is_relative_to(resolved_root):
        _log.debug("Output directory %s escapes project root %s", docs_path, resolved_root)
        return "", ""
    # Attempt to create the output directory tree
    try:
        docs_path.mkdir(parents=True, exist_ok=True)
    except OSError as mkdir_error:
        # Log failure and signal that the output directory is unavailable
        _log.debug("Cannot create output directory %s: %s", docs_path, mkdir_error)
        return "", ""

    # Skip logs directory creation if change logging is disabled
    if not log_structure_changes:
        return str(docs_path), ""

    # Create the logs directory if change logging is enabled
    logs_path = resolved_root / log_dir
    # Reject paths that escape the project root via traversal sequences
    if not logs_path.resolve().is_relative_to(resolved_root):
        _log.debug("Logs directory %s escapes project root %s", logs_path, resolved_root)
        return str(docs_path), ""
    # Attempt to create the logs directory tree
    try:
        logs_path.mkdir(parents=True, exist_ok=True)
    except OSError as mkdir_error:
        # Degrade gracefully; structure file still saved without change logs
        _log.debug("Cannot create logs directory %s: %s", logs_path, mkdir_error)
        return str(docs_path), ""

    return str(docs_path), str(logs_path)
