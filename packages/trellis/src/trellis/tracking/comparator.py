"""
Signature-level comparison of structure elements between runs.

Compare per-file code elements extracted by ``analyze_structure_elements``
and categorize changes by collaboration impact.

Classes
-------
ApiChange : A public function/class whose signature changed between runs.
ApiEntry : A public function/class that was added or removed.
StructureChanges : Categorized structural changes between two runs.

Functions
---------
strip_lineno : Strip the ``:NN`` line number suffix from an element line.
extract_lineno : Extract ``:NN`` from an element line, or empty string if absent.
extract_signature_detail : Extract the params/return portion from an element line.
compare_structure_elements : Compare old and new element maps and return categorized changes.

Examples
--------
>>> strip_lineno("def run() -> None  :42")
'def run() -> None'

>>> extract_lineno("def run() -> None  :42")
':42'

"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

_log = logging.getLogger(__name__)


# ====================================== #
#              DATA TYPES                #
# ====================================== #


class ApiChange(NamedTuple):
    """
    A public function/class whose signature changed between runs.

    Attributes
    ----------
    file_path : str
        Relative path key (e.g. ``"tracking/handlers.py"``).
    old_signature : str
        Normalized old element line.
    new_signature : str
        Normalized new element line.

    """

    file_path: str
    old_signature: str
    new_signature: str


class ApiEntry(NamedTuple):
    """
    A public function/class that was added or removed.

    Attributes
    ----------
    file_path : str
        Relative path key (e.g. ``"tracking/handlers.py"``).
    signature : str
        Normalized element line.

    """

    file_path: str
    signature: str


class StructureChanges(NamedTuple):
    """
    Categorized structural changes between two runs.

    Attributes
    ----------
    api_changes : list[ApiChange]
        Modified signatures in existing files.
    new_api : list[ApiEntry]
        New functions/classes.
    removed_api : list[ApiEntry]
        Removed functions/classes.
    new_packages : list[str]
        New package directories.
    removed_packages : list[str]
        Removed package directories.
    new_modules : list[str]
        New ``.py`` files.
    removed_modules : list[str]
        Removed ``.py`` files.
    new_files : list[str]
        New non-Python files (docs, configs, data).
    removed_files : list[str]
        Removed non-Python files.
    has_changes : bool
        True if any category is non-empty.

    """

    api_changes: list[ApiChange]
    new_api: list[ApiEntry]
    removed_api: list[ApiEntry]
    new_packages: list[str]
    removed_packages: list[str]
    new_modules: list[str]
    removed_modules: list[str]
    new_files: list[str]
    removed_files: list[str]
    has_changes: bool


# ====================================== #
#           ELEMENT PARSING              #
# ====================================== #


# Regex to extract element name from normalized lines (decorator | wrapped | def/class name).
_NAME_PATTERN = re.compile(
    r"^(?:.*\| )?(?:/wrapper\\ )?(?:async def |def |class )(\w+)",
)

# Regex to match line number suffix at end of element lines (e.g., "  :42").
_LINENO_SUFFIX = re.compile(r"  :\d+$")


def _extract_element_name(element_line: str) -> str:
    """
    Extract the function/class name from a normalized element line.

    Parameters
    ----------
    element_line : str
        A normalized code element line (may include ``  :NN`` suffix).

    Returns
    -------
    str
        The extracted name, or the full line if parsing fails.

    """
    stripped = strip_lineno(element_line)
    match = _NAME_PATTERN.match(stripped)
    # Return the captured name when the pattern matches; fall back to the full line
    if match:
        return match.group(1)
    return element_line


def strip_lineno(element_line: str) -> str:
    """
    Strip the ``:NN`` line number suffix from an element line.

    Parameters
    ----------
    element_line : str
        Element line that may end with ``  :NN``.

    Returns
    -------
    str
        Line without the line number suffix.

    """
    return _LINENO_SUFFIX.sub("", element_line)


def extract_lineno(element_line: str) -> str:
    """
    Extract ``:NN`` from an element line, or empty string if absent.

    Parameters
    ----------
    element_line : str
        Element line that may end with ``  :NN``.

    Returns
    -------
    str
        The ``:NN`` portion (e.g. ``":42"``), or ``""`` if absent.

    """
    match = _LINENO_SUFFIX.search(element_line)
    # Return the matched suffix without leading whitespace; empty string when absent
    if match:
        return match.group(0).lstrip()
    return ""


def extract_signature_detail(element_line: str) -> str:
    """
    Extract the params/return portion from an element line.

    Parameters
    ----------
    element_line : str
        A normalized code element line.

    Returns
    -------
    str
        The signature detail after the name.

    """
    stripped = strip_lineno(element_line)
    # Remove decorator prefix: "@... | "
    if " | " in stripped:
        stripped = stripped.rsplit(" | ", 1)[-1]
    # Remove "def name" or "class name" or "async def name" prefix
    match = re.match(r"(?:async def |def |class )\w+", stripped)
    if match:
        return stripped[match.end() :]
    return ""


# ====================================== #
#        STRUCTURE COMPARISON            #
# ====================================== #


def _collect_path_entries(
    paths: list[str],
    elements: dict[str, list[str]],
) -> list[ApiEntry]:
    """
    Collect API entries from .py files in a path list.

    Parameters
    ----------
    paths : list[str]
        File/directory paths to inspect.
    elements : dict[str, list[str]]
        Element map to look up signatures.

    Returns
    -------
    list[ApiEntry]
        Entries for all .py files found in the path list.

    """
    entries: list[ApiEntry] = []
    # Collect API entries only from Python files that have element data
    for path in paths:
        # Include only Python files present in the element map
        if path.endswith(".py") and path in elements:
            entries.extend(ApiEntry(path, signature) for signature in elements[path])
    return entries


def _build_element_map(lines: list[str], file_path: str) -> dict[str, str]:
    """
    Build a name-to-line mapping, logging collisions at DEBUG level.

    Parameters
    ----------
    lines : list[str]
        Element lines to index.
    file_path : str
        File path for collision log messages.

    Returns
    -------
    dict[str, str]
        Mapping of element names to their full lines. On collision,
        the last occurrence wins.

    """
    by_name: dict[str, str] = {}
    # Index each element by its extracted name for signature comparison
    for line in lines:
        name = _extract_element_name(line)
        # Log when a name collision occurs; last occurrence wins
        if name in by_name:
            _log.debug(
                "Element name collision in %s: %r appears multiple times",
                file_path,
                name,
            )
        by_name[name] = line
    return by_name


def _diff_file_elements(
    file_path: str,
    old_lines: list[str],
    new_lines: list[str],
) -> tuple[list[ApiChange], list[ApiEntry], list[ApiEntry]]:
    """
    Diff elements within a single file.

    Line number suffixes (``:NN``) are stripped before comparison so
    that pure line-number shifts do not register as changes.

    Parameters
    ----------
    file_path : str
        Relative path key for output.
    old_lines : list[str]
        Previous element lines.
    new_lines : list[str]
        Current element lines.

    Returns
    -------
    tuple[list[ApiChange], list[ApiEntry], list[ApiEntry]]
        Changes, additions, and removals within this file.

    """
    old_by_name = _build_element_map(old_lines, file_path)
    new_by_name = _build_element_map(new_lines, file_path)

    changes: list[ApiChange] = []
    added: list[ApiEntry] = []
    removed: list[ApiEntry] = []

    # Categorize each element as changed, added, or removed
    for name in sorted(set(old_by_name) | set(new_by_name)):
        is_in_old = name in old_by_name
        is_in_new = name in new_by_name
        if is_in_old and is_in_new:
            # Record as change only if the signature differs after stripping line numbers
            if strip_lineno(old_by_name[name]) != strip_lineno(new_by_name[name]):
                changes.append(ApiChange(file_path, old_by_name[name], new_by_name[name]))
        elif is_in_new:
            # Element only in new version; record as addition
            added.append(ApiEntry(file_path, new_by_name[name]))
        else:
            # Element only in old version; record as removal
            removed.append(ApiEntry(file_path, old_by_name[name]))

    return changes, added, removed


def _split_paths(paths: list[str]) -> tuple[list[str], list[str], list[str]]:
    """
    Split paths into packages, modules, and project file paths.

    Parameters
    ----------
    paths : list[str]
        All added or removed path keys.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        (packages, modules, files); packages are directories
        (ending with ``/``), modules are ``.py`` files, and files
        are everything else.

    """
    packages: list[str] = []
    modules: list[str] = []
    files: list[str] = []
    # Classify each path by its suffix into the appropriate category
    for path in paths:
        if path.endswith("/"):
            # Directory paths are package entries
            packages.append(path)
        elif path.endswith(".py"):
            # Python files are module entries
            modules.append(path)
        else:
            # Everything else is a non-Python project file
            files.append(path)
    return packages, modules, files


def compare_structure_elements(
    old_elements: dict[str, list[str]],
    new_elements: dict[str, list[str]],
    added_file_paths: list[str],
    removed_file_paths: list[str],
) -> StructureChanges:
    """
    Compare old and new element maps and return categorized changes.

    Parameters
    ----------
    old_elements : dict[str, list[str]]
        Per-file code elements from the previous run.
    new_elements : dict[str, list[str]]
        Per-file code elements from the current run.
    added_file_paths : list[str]
        File/directory paths added since last run.
    removed_file_paths : list[str]
        File/directory paths removed since last run.

    Returns
    -------
    StructureChanges
        Categorized structural changes.

    """
    api_changes: list[ApiChange] = []
    new_api = _collect_path_entries(added_file_paths, new_elements)
    removed_api = _collect_path_entries(removed_file_paths, old_elements)

    added_set = set(added_file_paths)
    removed_set = set(removed_file_paths)

    # Compare elements in files present in both old and new
    for path in sorted(set(old_elements) & set(new_elements)):
        # Skip files already categorized as added or removed to avoid double-counting
        if path in added_set or path in removed_set:
            continue
        changes, added, removed = _diff_file_elements(path, old_elements[path], new_elements[path])
        api_changes.extend(changes)
        new_api.extend(added)
        removed_api.extend(removed)

    new_packages, new_modules, new_files = _split_paths(added_file_paths)
    removed_packages, removed_modules, removed_files = _split_paths(removed_file_paths)

    has_changes = bool(
        api_changes or new_api or removed_api or added_file_paths or removed_file_paths
    )

    return StructureChanges(
        api_changes=api_changes,
        new_api=new_api,
        removed_api=removed_api,
        new_packages=new_packages,
        removed_packages=removed_packages,
        new_modules=new_modules,
        removed_modules=removed_modules,
        new_files=new_files,
        removed_files=removed_files,
        has_changes=has_changes,
    )
