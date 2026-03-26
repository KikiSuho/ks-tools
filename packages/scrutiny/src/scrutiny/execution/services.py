"""
File discovery and project-root services for scrutiny.

Provide project-root discovery, cache management, recursive Python-file
discovery, and PATH-aware executable location.

Classes
-------
ProjectRootService : Upward-search project-root discovery.
FileDiscoveryService : Recursive Python-file discovery.

Functions
---------
clear_tool_caches : Remove matching cache directories under a root.
which : PATH-aware executable locator.

Examples
--------
>>> result = which("python")
>>> result is not None
True

"""

from __future__ import annotations

import functools
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from scrutiny.core.exceptions import SCRProjectRootError
from scrutiny.platforms import get_extra_search_dirs, get_pathext, safe_rmtree

if TYPE_CHECKING:
    from scrutiny.configs.dataclasses import GlobalConfig
    from scrutiny.output.logger import SCRLogger

# ====================================== #
#           FILE DISCOVERY               #
# ====================================== #

# Directories universally irrelevant to code analysis.  These are
# always excluded during file discovery regardless of user settings.
# Sourced from Ruff / Bandit defaults plus obvious additions.
_STANDARD_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        # Version control
        ".git",
        ".git-rewrite",
        ".hg",
        ".svn",
        ".bzr",
        "CVS",
        # Python runtime / build
        "__pycache__",
        "dist",
        "build",
        "_build",
        ".eggs",
        "__pypackages__",
        "site-packages",
        # Virtual environments
        ".venv",
        "venv",
        ".direnv",
        # Tool caches
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pytype",
        ".tox",
        ".nox",
        ".pants.d",
        "buck-out",
        # IDE / editor
        ".idea",
        ".vscode",
        # Non-Python
        "node_modules",
        # Workspace
        ".claude",
    }
)

# Cache directories cleared by ``--clear-cache``.
_CACHE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
    }
)


class ProjectRootService:
    """
    Discover the project root directory.

    Supports two modes:

    * **Fixed root** (``current_dir_as_root=True``): treat the
      invocation directory as root, skipping upward search.
    * **Upward search** (``current_dir_as_root=False``): walk parent
      directories looking for project markers (e.g. ``.git``,
      ``pyproject.toml``).

    This is ``scrutiny``'s built-in root discovery.  It is
    completely independent of ``project_root.py``.

    Attributes
    ----------
    PROJECT_MARKERS : tuple[str, ...]
        File and directory names that indicate a project root.

    """

    PROJECT_MARKERS: tuple[str, ...] = (
        ".git",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        ".hg",
        ".svn",
    )

    @staticmethod
    def get_project_root(
        start_path: Path,
        global_config: GlobalConfig,
    ) -> Path:
        """
        Return the effective project root.

        When ``current_dir_as_root`` is True, returns *start_path*
        directly.  Otherwise calls ``search_upward``.

        Parameters
        ----------
        start_path : Path
            Starting path (file or directory).
        global_config : GlobalConfig
            Configuration with search settings.

        Returns
        -------
        Path
            Resolved project root.

        """
        base = start_path if start_path.is_dir() else start_path.parent
        # Return the invocation directory directly when fixed-root mode is active
        if global_config.current_dir_as_root:
            return base.resolve()
        return ProjectRootService.search_upward(
            base,
            max_depth=global_config.max_upward_search_depth,
            follow_symlinks=global_config.follow_symlinks,
        )

    @staticmethod
    def get_actual_project_root(
        start_path: Path,
        global_config: GlobalConfig,
    ) -> Path:
        """
        Perform upward search unconditionally, ignoring ``current_dir_as_root``.

        Used for log file placement -- logs should always go in the
        real project root, not a sub-directory.

        Parameters
        ----------
        start_path : Path
            Starting path.
        global_config : GlobalConfig
            Configuration with search depth.

        Returns
        -------
        Path
            Resolved actual project root.

        Raises
        ------
        SCRProjectRootError
            If no project markers are found during upward search.

        """
        base = start_path if start_path.is_dir() else start_path.parent
        return ProjectRootService.search_upward(
            base,
            max_depth=global_config.max_upward_search_depth,
            follow_symlinks=global_config.follow_symlinks,
        )

    @staticmethod
    def _marker_exists(
        directory: Path,
        marker: str,
        follow_symlinks: bool,
    ) -> bool:
        """
        Check whether a project marker exists in *directory*.

        Parameters
        ----------
        directory : Path
            Directory to check.
        marker : str
            Marker file or directory name (e.g. ``".git"``).
        follow_symlinks : bool
            Whether to follow symlinks when checking.

        Returns
        -------
        bool
            ``True`` if the marker exists, ``False`` otherwise.

        """
        candidate = directory / marker
        # Check existence; catch filesystem errors to avoid aborting on broken paths
        try:
            # Choose symlink-following or non-following existence check
            if follow_symlinks:
                # exists() follows symlinks through to the target
                return candidate.exists()
            # lstat does not follow symlinks; FileNotFoundError means absent
            try:
                candidate.lstat()
                return True
            except FileNotFoundError:
                # Marker does not exist at this location
                return False
        except (OSError, PermissionError):
            # Treat inaccessible paths as non-existent
            return False

    @staticmethod
    def search_upward(
        start: Path,
        max_depth: int = 5,
        follow_symlinks: bool = False,
    ) -> Path:
        """
        Walk upward from *start* looking for project markers.

        Parameters
        ----------
        start : Path
            Directory to begin searching from.
        max_depth : int
            Maximum parent levels to traverse.
        follow_symlinks : bool
            Whether to follow symlinks during marker checking.

        Returns
        -------
        Path
            First directory containing a marker.

        Raises
        ------
        SCRProjectRootError
            If the starting path cannot be resolved or no markers are found.

        """
        # Resolve the starting path to an absolute location.
        try:
            # Convert to absolute path before traversal
            current = start.resolve()
        except (OSError, RuntimeError) as error:
            # Path resolution failed; cannot proceed with upward search
            raise SCRProjectRootError(
                f"Cannot resolve starting path '{start}': {error}",
            ) from error

        # Walk up the directory tree checking for project markers.
        for _ in range(max_depth):
            # Check each project marker in the current directory
            for marker in ProjectRootService.PROJECT_MARKERS:
                # Return immediately when a marker is found
                if ProjectRootService._marker_exists(current, marker, follow_symlinks):
                    return current

            # Stop at filesystem root (parent == self).
            parent = current.parent
            if parent == current:
                break
            current = parent

        raise SCRProjectRootError(
            f"No project markers found searching upward from '{start}'",
        )


def _find_and_remove_caches(root: Path, logger: SCRLogger) -> list[str]:
    """
    Walk *root* once and remove all cache directories.

    Uses ``os.walk`` with in-place pruning to skip excluded directories
    (e.g. ``.git``, ``node_modules``) and avoid descending into cache
    directories after deletion.

    Parameters
    ----------
    root : Path
        Project root to search.
    logger : SCRLogger
        Logger for removal-failure warnings.

    Returns
    -------
    list[str]
        Relative paths of successfully removed directories.

    """
    # Directories to skip entirely during traversal.
    skip_dirs = _STANDARD_EXCLUDE_DIRS | _CACHE_DIR_NAMES
    cleared: list[str] = []
    # Walk the project tree, pruning excluded directories in place
    for dirpath_str, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        # Check for and remove each known cache directory name
        for cache_name in _CACHE_DIR_NAMES:
            candidate = Path(dirpath_str) / cache_name
            # Only attempt removal when the candidate actually exists as a directory
            if candidate.is_dir():
                # Remove the cache tree; log failures without aborting
                try:
                    safe_rmtree(candidate)
                    cleared.append(str(candidate.relative_to(root)))
                except OSError as removal_error:
                    # Log the failure and continue with remaining caches
                    logger.warning(f"Could not remove {candidate}: {removal_error}")
    return cleared


def clear_tool_caches(root: Path, logger: SCRLogger) -> None:
    """
    Delete tool cache directories under *root*.

    Walks the project tree and removes directories whose names match
    ``_CACHE_DIR_NAMES`` (``.mypy_cache``, ``.ruff_cache``,
    ``__pycache__``).

    Parameters
    ----------
    root : Path
        Project root to search.
    logger : SCRLogger
        Logger for status messages.

    """
    cleared = _find_and_remove_caches(root, logger)
    # Report what was removed, or note that nothing was found
    if cleared:
        # List each removed directory
        count = len(cleared)
        noun = "directory" if count == 1 else "directories"
        logger.info(f"Cleared {count} cache {noun}")
        # Emit each removed path for the verbose log
        for entry in cleared:
            logger.info(f"  Removed: {entry}")
    else:
        # No matching cache directories existed
        logger.info("No cache directories found to clear")


class FileDiscoveryService:
    """
    Discover Python files for analysis.

    Walks directories recursively, respecting both global and
    tool-specific exclusion patterns.
    """

    @staticmethod
    def discover_files(
        paths: list[Path],
        global_config: GlobalConfig,
        tool_exclusions: tuple[str, ...] = (),
    ) -> list[Path]:
        """
        Discover ``.py`` files from *paths*, respecting exclusions.

        Directly provided files are always included (exclusions apply
        only during directory traversal).

        Parameters
        ----------
        paths : list[Path]
            Starting paths (files or directories).
        global_config : GlobalConfig
            Configuration containing base exclusions.
        tool_exclusions : tuple[str, ...]
            Extra exclusion patterns specific to a tool.

        Returns
        -------
        list[Path]
            Sorted, deduplicated list of Python files.

        """
        # Merge all exclusion sources into a single lookup set.
        combined_exclusions: set[str] = (
            set(_STANDARD_EXCLUDE_DIRS)
            | set(global_config.exclude_dirs)
            | set(global_config.exclude_files)
            | set(tool_exclusions)
        )
        discovered: list[Path] = []

        # Process each starting path as either a direct file or directory to walk
        for path in paths:
            # Resolve to absolute; skip paths that cannot be resolved
            try:
                resolved = path.resolve()
            except (OSError, RuntimeError):
                # Unresolvable path; skip silently
                continue

            # Directly provided files bypass exclusion filtering.
            if resolved.is_file():
                if resolved.suffix.lower() == ".py":
                    discovered.append(resolved)
                continue

            # Recursively walk directories, applying exclusions.
            if resolved.is_dir():
                discovered.extend(
                    FileDiscoveryService._walk_directory(
                        resolved,
                        combined_exclusions,
                        global_config.follow_symlinks,
                    ),
                )

        # Deduplicate and sort for deterministic ordering.
        return sorted(set(discovered))

    @staticmethod
    def _should_skip_entry(path_entry: Path, exclusions: set[str], follow_symlinks: bool) -> bool:
        """
        Return True if *path_entry* should be skipped during directory walk.

        Parameters
        ----------
        path_entry : Path
            Filesystem entry to evaluate.
        exclusions : set[str]
            File and directory names to skip.
        follow_symlinks : bool
            Whether to follow symbolic links.

        Returns
        -------
        bool
            True when the entry should be skipped.

        """
        # Skip symbolic links when the config does not follow them
        if path_entry.is_symlink() and not follow_symlinks:
            return True
        return path_entry.name in exclusions

    @staticmethod
    def _walk_directory(
        directory_root: Path,
        exclusions: set[str],
        follow_symlinks: bool,
        *,
        max_depth: int = 50,
    ) -> list[Path]:
        """
        Recursively walk *directory_root*, collecting ``.py`` files.

        Parameters
        ----------
        directory_root : Path
            Directory to walk.
        exclusions : set[str]
            File and directory names to skip.
        follow_symlinks : bool
            Whether to follow symbolic links.
        max_depth : int
            Maximum recursion depth (default 50).  Stops recursing
            when depth reaches 0.

        Returns
        -------
        list[Path]
            Python files found under *directory_root*.

        """
        # Stop recursing when the depth limit is reached
        if max_depth <= 0:
            return []

        files: list[Path] = []

        # List directory contents; return empty on access failure
        try:
            items = list(directory_root.iterdir())
        except (PermissionError, OSError):
            # Directory is inaccessible; return what we have
            return files

        # Process each entry: collect .py files, recurse into subdirectories
        for path_entry in items:
            # Guard against filesystem errors on individual entries
            try:
                # Skip excluded names and unfollowed symlinks
                if FileDiscoveryService._should_skip_entry(path_entry, exclusions, follow_symlinks):
                    continue
                # Collect Python files; recurse into subdirectories.
                if path_entry.is_file() and path_entry.suffix.lower() == ".py":
                    # Python source file; add to results
                    files.append(path_entry)
                elif path_entry.is_dir():
                    # Subdirectory; recurse with decremented depth
                    files.extend(
                        FileDiscoveryService._walk_directory(
                            path_entry,
                            exclusions,
                            follow_symlinks,
                            max_depth=max_depth - 1,
                        ),
                    )
            except (PermissionError, OSError):
                # Skip inaccessible entries silently
                continue

        return files


@functools.cache
def which(command_name: str) -> Optional[str]:
    """
    Find *command_name* on PATH, returning its absolute path or ``None``.

    A pure-string replacement for ``shutil.which`` that avoids the
    Windows ``PathLike`` bug present before Python 3.12.

    In addition to the standard ``PATH``, the directory containing the
    running Python interpreter (``sys.executable``) is checked first.
    This ensures tools installed in a conda / virtualenv ``Scripts``
    or ``bin`` directory are discovered even when the environment has
    not been fully activated (e.g., when an IDE invokes the interpreter
    directly).

    Parameters
    ----------
    command_name : str
        Executable name to locate.

    Returns
    -------
    Optional[str]
        Absolute path to the executable, or ``None`` if not found.

    """
    # Start with the interpreter's own directory so conda/venv tools
    # are found even when Scripts/ is not on PATH.
    interpreter_dir = str(Path(sys.executable).resolve().parent)
    path_dirs = os.environ.get("PATH", os.defpath).split(os.pathsep)
    # Prepend interpreter directory so conda/venv tools are found first
    if interpreter_dir not in path_dirs:
        path_dirs.insert(0, interpreter_dir)

    # On Windows, also check the Scripts sub-directory next to the
    # interpreter (e.g. ``envs/ks_backend/Scripts``).
    for idx, extra_dir in enumerate(get_extra_search_dirs(interpreter_dir)):
        # Insert extra directories after the interpreter dir, preserving order
        if extra_dir not in path_dirs:
            path_dirs.insert(1 + idx, extra_dir)
    pathext = get_pathext()

    # Search each directory for an executable matching command_name.
    for directory in path_dirs:
        # Try each executable extension (empty string on POSIX, .exe/.cmd on Windows)
        for ext in pathext:
            candidate = Path(directory) / (command_name + ext)
            # Stat the candidate; skip on any filesystem error
            try:
                file_stat = candidate.stat()
            except (OSError, ValueError):
                # Candidate does not exist or path is invalid
                continue
            # Return the first regular file with execute permission
            if stat.S_ISREG(file_stat.st_mode) and os.access(candidate, os.X_OK):
                return str(candidate)
    return None
