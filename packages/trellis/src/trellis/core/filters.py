"""
Filtering predicates for directory scanning and change detection.

Provide all include/exclude logic used during directory traversal and
change analysis. Every predicate accepts a ``FilterSettings`` snapshot
so that no function reads mutable global state.

Hard-ignore constants (``HARD_IGNORE_DIRS``, ``HARD_IGNORE_FILES``)
define infrastructure noise that is always filtered regardless of user
toggle settings. User-configurable patterns flow through
``FilterSettings`` and are gated by ``enable_ignore_dirs`` /
``enable_ignore_files``.

Constants
---------
HARD_IGNORE_DIRS : Directory names that are always excluded from scanning.
HARD_IGNORE_FILES : File patterns that are always excluded from scanning.

Functions
---------
should_skip_system_file : Check if an item is a system file that should never be shown.
is_docs_directory_visible : Check if a directory is the docs output directory and visible.
is_special_case_item : Check if an item overrides normal filtering rules.
should_ignore_directory : Check if a directory should be ignored based on configuration.
should_ignore_file : Check if a file should be ignored based on configuration.
matches_ignored_file : Check if a file path matches ignored file patterns.
matches_ignored_directory : Check if a directory path matches any ignore patterns.
directory_matches_pattern : Check if a single directory matches one ignore pattern.
is_path_filtered_by_flags : Check if a path should be ignored based on current filter settings.
is_path_in_ignored_hierarchy : Check if a path or any of its ancestors should be ignored.

Examples
--------
>>> should_skip_system_file("__init__.py")
True
>>> should_skip_system_file("utils.py")
False

"""

from __future__ import annotations

import fnmatch
import functools
import re
from collections.abc import Sequence
from pathlib import Path

from trellis.config import FilterSettings

# ====================================== #
#        HARD-IGNORE CONSTANTS           #
# ====================================== #

HARD_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        # Python runtime caches
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".black_cache",
        ".pytest_cache",
        ".hypothesis",
        # Version control internals
        ".git",
        ".svn",
        ".hg",
        # Virtual environments (Python interpreter copies)
        "venv",
        ".venv",
        "virtualenv",
        # Downloaded package trees
        "node_modules",
        "bower_components",
        # Package manager caches
        ".npm",
        ".yarn",
        # Tool-generated directories
        ".tox",
        ".ipynb_checkpoints",
        "htmlcov",
        # Coverage data directory
        ".coverage",
        # OS metadata noise
        "__MACOSX",
    }
)

# Glob patterns for hard-ignored directories (checked via fnmatch).
_HARD_IGNORE_DIR_GLOBS: frozenset[str] = frozenset(
    {
        "*.egg-info",
        "*.eggs",
    }
)

HARD_IGNORE_FILES: frozenset[str] = frozenset(
    {
        # Compiled Python bytecode
        "*.pyc",
        "*.pyo",
        "*.pyd",
        # Atomic write temporaries (orphaned on lock failure)
        "*.tmp",
        # Coverage data file
        ".coverage",
        # OS metadata noise
        ".DS_Store",
        # Windows reserved device name (AI tool artefact)
        "nul",
    }
)


# Pre-compile hard-ignore glob patterns into regex objects to avoid repeated
# fnmatch.translate + re.compile on every file/directory visit.
_HARD_IGNORE_DIR_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(fnmatch.translate(pat)) for pat in _HARD_IGNORE_DIR_GLOBS
)
_HARD_IGNORE_FILE_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(fnmatch.translate(pat)) for pat in HARD_IGNORE_FILES
)


_PATTERN_CACHE_SIZE = 8


@functools.lru_cache(maxsize=_PATTERN_CACHE_SIZE)
def _compile_patterns(patterns: frozenset[str]) -> tuple[re.Pattern[str], ...]:
    """
    Compile a frozenset of fnmatch glob patterns into regex objects.

    Results are cached by the frozen pattern set, so repeated calls with
    the same ``FilterSettings`` patterns avoid recompilation.

    Parameters
    ----------
    patterns : frozenset[str]
        Glob patterns to compile.

    Returns
    -------
    tuple[re.Pattern[str], ...]
        Pre-compiled regex objects.

    """
    return tuple(re.compile(fnmatch.translate(pat)) for pat in patterns)


_SINGLE_PATTERN_CACHE_SIZE = 32


@functools.lru_cache(maxsize=_SINGLE_PATTERN_CACHE_SIZE)
def _compile_single_pattern(pattern: str) -> re.Pattern[str]:
    """
    Compile a single fnmatch glob pattern into a regex object.

    Cached per pattern string to avoid repeated compilation in
    ``directory_matches_pattern`` without polluting the frozenset cache.

    Parameters
    ----------
    pattern : str
        Glob pattern to compile.

    Returns
    -------
    re.Pattern[str]
        Compiled regex object.

    """
    return re.compile(fnmatch.translate(pattern))


@functools.lru_cache(maxsize=_PATTERN_CACHE_SIZE)
def _partition_dir_patterns(
    patterns: frozenset[str],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """
    Partition directory ignore patterns into exact-match and complex groups.

    Exact-match patterns (no slash, no glob chars) can use fast set lookup.
    Complex patterns (containing ``/``, ``*``, ``?``, or ``[``) require
    per-pattern matching via ``directory_matches_pattern``.

    Parameters
    ----------
    patterns : frozenset[str]
        Directory ignore patterns to partition.

    Returns
    -------
    tuple[frozenset[str], tuple[str, ...]]
        ``(exact_matches, complex_patterns)`` where exact matches are
        plain directory names and complex patterns need path context.

    """
    _glob_chars = frozenset("*?[")
    exact: list[str] = []
    complex_pats: list[str] = []
    # Classify each pattern based on whether it needs path or glob matching
    for pattern in patterns:
        if "/" in pattern or any(char in pattern for char in _glob_chars):
            # Patterns with path separators or wildcards need full matching
            complex_pats.append(pattern)
        else:
            # Plain names can be checked via set membership
            exact.append(pattern)
    return frozenset(exact), tuple(complex_pats)


def _extract_basename(path: str, *, strip_trailing_sep: bool = False) -> str:
    r"""
    Extract the basename from a path without allocating a Path object.

    Parameters
    ----------
    path : str
        File or directory path.
    strip_trailing_sep : bool, optional
        Whether to strip trailing ``/`` and ``\\`` before extracting.
        Default is False.

    Returns
    -------
    str
        The basename portion of the path.

    """
    # Strip trailing path separators before extracting the basename
    if strip_trailing_sep:
        path = path.rstrip("/\\")
    sep_index = max(path.rfind("/"), path.rfind("\\"))
    return path[sep_index + 1 :] if sep_index >= 0 else path


def _matches_hard_ignore(path: str, *, is_directory: bool) -> bool:
    """
    Check if a path's basename matches a hard-ignore pattern unconditionally.

    Checks the basename against directory patterns if ``is_directory=True``,
    or file patterns otherwise.

    Parameters
    ----------
    path : str
        File or directory path to check (only the basename is matched).
    is_directory : bool
        Whether the path refers to a directory. Selects which pattern set
        (directory or file) is used for matching.

    Returns
    -------
    bool
        True if the basename matches a hard-ignore pattern.

    """
    name = _extract_basename(path)
    # Check directory-specific patterns when the path is a directory
    if is_directory:
        # Check against exact directory names first, then glob patterns
        if name in HARD_IGNORE_DIRS:
            return True
        return any(regex.match(name) for regex in _HARD_IGNORE_DIR_REGEXES)
    return any(regex.match(name) for regex in _HARD_IGNORE_FILE_REGEXES)


def _matches_hard_ignore_any(path: str) -> bool:
    """
    Check if a path's basename matches any hard-ignore pattern (dir or file).

    Used by ``is_path_filtered_by_flags`` where the path type is unknown.
    Extracts the basename once and checks both directory and file patterns.

    Parameters
    ----------
    path : str
        Path to check (only the basename is matched).

    Returns
    -------
    bool
        True if the basename matches any hard-ignore pattern.

    """
    name = _extract_basename(path, strip_trailing_sep=True)
    # Check against exact directory names
    if name in HARD_IGNORE_DIRS:
        return True
    # Check against directory glob patterns
    if any(regex.match(name) for regex in _HARD_IGNORE_DIR_REGEXES):
        return True
    return any(regex.match(name) for regex in _HARD_IGNORE_FILE_REGEXES)


# ====================================== #
#         SCANNING PREDICATES            #
# ====================================== #


def should_skip_system_file(item: str) -> bool:
    """
    Check if an item is a system file that should never be shown.

    Parameters
    ----------
    item : str
        The file or directory name to check.

    Returns
    -------
    bool
        True if the item should be skipped, False otherwise.

    """
    return item in ("__init__.py", "__main__.py", "py.typed")


def is_docs_directory_visible(directory_name: str, settings: FilterSettings) -> bool:
    """
    Check if a directory is the configured docs output directory and visible.

    Parameters
    ----------
    directory_name : str
        Base name of the directory to check.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the directory matches the configured output directory
        and SHOW_DOCS is enabled.

    """
    return directory_name == settings.output_dir and settings.show_docs


def is_special_case_item(item_name: str, is_directory: bool, settings: FilterSettings) -> bool:
    """
    Check if an item is a special case that overrides normal filtering.

    Parameters
    ----------
    item_name : str
        The base name of the item.
    is_directory : bool
        Whether the item is a directory.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if this is a special case that should be included regardless
        of normal filtering rules.

    """
    return is_directory and is_docs_directory_visible(item_name, settings)


def should_ignore_directory(directory_path: str, settings: FilterSettings) -> bool:
    """
    Check if a directory should be ignored based on configuration.

    Parameters
    ----------
    directory_path : str
        Full path to the directory to check.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the directory should be ignored, False otherwise.

    """
    # Always block hard-ignore directories regardless of user settings
    if _matches_hard_ignore(directory_path, is_directory=True):
        return True
    # Allow all directories through when user ignore patterns are disabled
    if not settings.enable_ignore_dirs:
        return False
    return matches_ignored_directory(directory_path, settings)


def should_ignore_file(item_path: str, settings: FilterSettings) -> bool:
    """
    Check if a file should be ignored based on configuration.

    This includes both explicit file ignore patterns and documentation
    file filtering based on SHOW_DOCS setting.

    Parameters
    ----------
    item_path : str
        The full path to the file.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the file should be ignored, False otherwise.

    """
    # Always block hard-ignore file patterns regardless of user settings
    if _matches_hard_ignore(item_path, is_directory=False):
        return True
    # Check user-configured file patterns when enabled
    if settings.enable_ignore_files and matches_ignored_file(item_path, settings):
        return True
    # Filter documentation files when SHOW_DOCS is disabled
    return _is_doc_file_filtered(item_path, settings)


def matches_ignored_file(file_path: str, settings: FilterSettings) -> bool:
    """
    Check if a file path matches ignored file patterns.

    Parameters
    ----------
    file_path : str
        Full path to the file to check against ignore patterns.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the file matches an ignored pattern, False otherwise.

    """
    filename = Path(file_path).name
    compiled = _compile_patterns(settings.ignore_files)
    return any(regex.match(filename) for regex in compiled)


def directory_matches_pattern(directory_name: str, normalized_posix: str, pattern: str) -> bool:
    """
    Check if a single directory matches one ignore pattern.

    Parameters
    ----------
    directory_name : str
        Base name of the directory.
    normalized_posix : str
        Full path in POSIX format for path-pattern matching.
    pattern : str
        Ignore pattern to test against.

    Returns
    -------
    bool
        True if the directory matches the pattern.

    """
    # Slash patterns match against the full POSIX path, not just the basename
    if "/" in pattern:
        return normalized_posix == pattern or normalized_posix.endswith(f"/{pattern}")
    # Glob patterns are compiled to regex via per-pattern LRU cache
    if any(char in pattern for char in "*?["):
        return _compile_single_pattern(pattern).match(directory_name) is not None
    return directory_name == pattern


def matches_ignored_directory(path: str, settings: FilterSettings) -> bool:
    """
    Check if a directory path matches any ignore patterns.

    Parameters
    ----------
    path : str
        Directory path to check.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if directory should be ignored, False otherwise.

    """
    directory_name = _extract_basename(path, strip_trailing_sep=True)

    # Special case for the configured docs output directory when SHOW_DOCS is enabled.
    if is_docs_directory_visible(directory_name, settings):
        return False

    # Fast path: check exact-match patterns via set lookup before iterating
    exact_matches, complex_patterns = _partition_dir_patterns(settings.ignore_dirs)
    if directory_name in exact_matches:
        return True

    # Slow path: check slash and glob patterns that require full path context
    if complex_patterns:
        normalized_posix = Path(path).as_posix()
        return any(
            directory_matches_pattern(directory_name, normalized_posix, pattern)
            for pattern in complex_patterns
        )
    return False


# ====================================== #
#     CHANGE DETECTION PREDICATES        #
# ====================================== #


def is_path_filtered_by_flags(path: str, settings: FilterSettings) -> bool:
    """
    Check if a path should be ignored based on current filter settings.

    This function determines whether a path should be excluded from analysis
    by checking it against the current ignore lists and their enable flags.

    Parameters
    ----------
    path : str
        Path to check against ignore rules.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the path should be ignored according to current settings,
        False otherwise.

    """
    # Hard ignores are checked unconditionally, before any enable flags. Both dir and file patterns
    # are tested since path type is unknown in change detection context.
    if _matches_hard_ignore_any(path):
        return True

    # User-configurable ignore patterns, gated by enable flags.
    if settings.enable_ignore_dirs and matches_ignored_directory(path, settings):
        return True
    # Check user-configurable file ignore patterns when enabled
    if settings.enable_ignore_files and matches_ignored_file(path, settings):
        return True

    # Filter documentation files when SHOW_DOCS is disabled.
    return _is_doc_file_filtered(path, settings)


def is_path_in_ignored_hierarchy(
    path: str, path_ancestry: Sequence[str], settings: FilterSettings
) -> bool:
    """
    Check if a path or any of its ancestors should be ignored.

    Parameters
    ----------
    path : str
        The path to check.
    path_ancestry : Sequence[str]
        Ancestor paths for the current path.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if path or any ancestor should be ignored.

    """
    # Check the path itself before walking its ancestry chain
    if is_path_filtered_by_flags(path, settings):
        return True
    return any(is_path_filtered_by_flags(ancestor, settings) for ancestor in path_ancestry)


def _is_doc_file_filtered(path: str, settings: FilterSettings) -> bool:
    """
    Check if a path is a documentation file that should be filtered.

    Parameters
    ----------
    path : str
        Path to check.
    settings : FilterSettings
        Current filter settings snapshot.

    Returns
    -------
    bool
        True if the path is a doc file and SHOW_DOCS is disabled.

    """
    # Filter documentation files only when SHOW_DOCS is disabled
    if not settings.show_docs:
        extension = Path(path).suffix
        # Match the file extension against known documentation extensions
        if extension.lower() in settings.doc_extensions:
            return True
    return False
