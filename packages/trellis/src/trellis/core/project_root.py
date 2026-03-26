"""
Standalone project root discovery utility.

Walk upward from a starting directory to find the project root by looking
for well-known marker files and directories. Designed as a portable,
copy-paste module with zero external dependencies.

Passing ``__file__`` ensures the search starts from the calling module's
directory rather than the current working directory.

Constants
---------
Preference : Literal type alias for ``"vcs"`` or ``"config"`` preference values.
DEFAULT_MARKERS : Combined marker list (``VCS_MARKERS + CONFIG_MARKERS``).
VCS_MARKERS : Marker names associated with VCS roots.
CONFIG_MARKERS : Marker names associated with project configuration roots.
DEFAULT_MAX_DEPTH : Default number of directory levels to search.
PREFERENCE_VCS : Preference value to prioritize VCS markers.
PREFERENCE_CONFIG : Preference value to prioritize config markers.

Functions
---------
find_project_root : Discover the project root from a starting path.

Examples
--------
>>> import tempfile, os
>>> tmp = tempfile.mkdtemp()
>>> os.makedirs(os.path.join(tmp, ".git"))
>>> result = find_project_root(start_path=tmp, markers=[".git"])
>>> result is not None
True

"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal, Optional, Union

Preference = Literal["vcs", "config"]

PREFERENCE_VCS: Final[Preference] = "vcs"
PREFERENCE_CONFIG: Final[Preference] = "config"

VCS_MARKERS: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
)

CONFIG_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "Cargo.toml",
    "package.json",
)

DEFAULT_MARKERS: tuple[str, ...] = VCS_MARKERS + CONFIG_MARKERS
DEFAULT_MAX_DEPTH: Final[int] = 8

_MarkersInput = Optional[Union[list[str], tuple[str, ...]]]
_StartPath = Optional[Union[Path, str, os.PathLike[str]]]


# ====================================== #
#          INPUT VALIDATION              #
# ====================================== #


def _validate_preference(preference: Optional[Preference]) -> Optional[Preference]:
    """
    Validate a preference value.

    Parameters
    ----------
    preference : {"vcs", "config"} or None
        Preference value to validate.

    Returns
    -------
    {"vcs", "config"} or None
        Normalized preference value.

    Raises
    ------
    ValueError
        If the preference value is invalid.

    """
    # Accept None as a valid no-preference value
    if preference is None:
        return None
    # Accept known preference values
    if preference in (PREFERENCE_VCS, PREFERENCE_CONFIG):
        return preference
    raise ValueError(
        f"Invalid preference {preference!r}. Use {PREFERENCE_VCS!r} or {PREFERENCE_CONFIG!r}."
    )


def _validate_max_depth(max_depth: int) -> int:
    """
    Validate the maximum search depth.

    Parameters
    ----------
    max_depth : int
        Number of directory levels inspected, including the starting directory.

    Returns
    -------
    int
        Validated maximum depth.

    Raises
    ------
    TypeError
        If ``max_depth`` is not an integer.
    ValueError
        If ``max_depth`` is less than 1.

    """
    # Reject bools explicitly since bool is a subclass of int.
    if not isinstance(max_depth, int) or isinstance(max_depth, bool):
        raise TypeError("max_depth must be an integer")
    # Reject depths below the minimum of 1
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    return max_depth


def _coerce_markers(markers: _MarkersInput) -> tuple[str, ...]:
    """
    Coerce marker input to a validated tuple of strings.

    Parameters
    ----------
    markers : list[str] or tuple[str, ...] or None
        Marker names whose presence indicates a project root. ``None`` uses
        ``DEFAULT_MARKERS``.

    Returns
    -------
    tuple[str, ...]
        Validated marker tuple.

    Raises
    ------
    TypeError
        If ``markers`` is not a list, tuple, or None.
        If ``markers`` contains non-string values.
    ValueError
        If ``markers`` is an empty sequence.
        If any marker is an empty or whitespace-only string.

    """
    # Fall back to the default marker set when no markers are given.
    if markers is None:
        # Use built-in defaults when caller provides no markers
        markers_tuple = DEFAULT_MARKERS
    elif isinstance(markers, (list, tuple)):
        # Convert list or tuple input to a normalized tuple
        markers_tuple = tuple(markers)
    else:
        # Reject unsupported input types
        raise TypeError("markers must be a list, tuple, or None")

    # Ensure every marker entry is a string.
    if not all(isinstance(marker, str) for marker in markers_tuple):
        raise TypeError("markers must contain only strings")

    # Reject empty sequences; an empty marker list can never match.
    if not markers_tuple:
        raise ValueError("markers must not be empty")

    # Reject empty or whitespace-only marker strings.
    if any(not marker.strip() for marker in markers_tuple):
        raise ValueError("markers must not contain empty or whitespace-only strings")

    return markers_tuple


def _reorder_by_preference(
    markers_tuple: tuple[str, ...], preference: Preference
) -> tuple[str, ...]:
    """
    Reorder markers so preferred category comes first.

    Parameters
    ----------
    markers_tuple : tuple[str, ...]
        Validated marker tuple.
    preference : {"vcs", "config"}
        Category to prioritize.

    Returns
    -------
    tuple[str, ...]
        Reordered marker tuple.

    """
    # Build a set of the preferred category for fast membership tests.
    preferred_set = set(VCS_MARKERS) if preference == PREFERENCE_VCS else set(CONFIG_MARKERS)

    # Partition markers while preserving their original relative order.
    preferred = [marker for marker in markers_tuple if marker in preferred_set]
    remaining = [marker for marker in markers_tuple if marker not in preferred_set]
    return tuple(preferred + remaining)


def _normalize_markers(markers: _MarkersInput, preference: Optional[Preference]) -> tuple[str, ...]:
    """
    Normalize marker inputs and apply preference ordering.

    Parameters
    ----------
    markers : list[str] or tuple[str, ...] or None
        Marker names whose presence indicates a project root. ``None`` uses
        ``DEFAULT_MARKERS``.
    preference : {"vcs", "config"} or None
        Prioritize VCS or config markers while preserving input order.

    Returns
    -------
    tuple[str, ...]
        Normalized marker list.

    Raises
    ------
    TypeError
        If ``markers`` is not a list, tuple, or None.
        If ``markers`` contains non-string values.
    ValueError
        If ``markers`` is an empty sequence.
        If any marker is an empty or whitespace-only string.
        If ``preference`` is invalid.

    """
    # Coerce and validate inputs before applying any reordering.
    markers_tuple = _coerce_markers(markers)
    preference = _validate_preference(preference)

    # Skip reordering when no preference is specified.
    if preference is None:
        return markers_tuple

    return _reorder_by_preference(markers_tuple, preference)


# ====================================== #
#       PROJECT ROOT DISCOVERY           #
# ====================================== #


def find_project_root(
    start_path: _StartPath = None,
    markers: _MarkersInput = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    follow_symlinks: bool = False,
    preference: Optional[Preference] = None,
) -> Optional[Path]:
    """
    Walk upward from *start_path* looking for marker files or directories.

    Parameters
    ----------
    start_path : Path or str or os.PathLike or None, optional
        Directory to begin searching from. ``None`` uses the current
        working directory. For module-relative discovery, pass ``__file__``.
    markers : list[str] or tuple[str, ...] or None, optional
        File or directory names whose presence indicates a project root.
        ``None`` uses ``DEFAULT_MARKERS``. Checked in order at each level.
    max_depth : int, optional
        Number of directory levels inspected, including the starting directory.
        Default is 8.
    follow_symlinks : bool, optional
        Whether to resolve symlinks when checking for markers.
        Default is False.
    preference : {"vcs", "config"} or None, optional
        Prioritize VCS or config markers during normalization while preserving
        the input order.

    Returns
    -------
    Path or None
        Resolved project root path, or ``None`` if no marker was found
        within *max_depth* levels.

    Raises
    ------
    TypeError
        If ``markers`` is not a list, tuple, or None.
        If ``max_depth`` is not an integer.
    ValueError
        If ``preference`` is invalid.
        If ``max_depth`` is less than 1.

    """
    # Resolve the starting directory; use current working directory if not provided.
    current = Path.cwd().resolve() if start_path is None else Path(start_path).resolve()

    # Normalize and validate marker and depth parameters.
    markers_tuple = _normalize_markers(markers, preference)
    max_depth = _validate_max_depth(max_depth)

    # Ensure the search starts from a directory, not a file.
    if current.is_file():
        current = current.parent

    # Walk upward from the starting directory up to max_depth levels.
    for _ in range(max_depth):
        # Check each marker at the current level.
        for marker in markers_tuple:
            candidate = current / marker
            # Choose existence check strategy based on symlink policy
            if follow_symlinks:
                # Resolve symlinks and check if the target exists.
                is_marker_present = candidate.resolve().exists()
            else:
                # Check existence without following symlinks to avoid symlink loops.
                # Attempt lstat to detect the marker without resolving symlinks
                try:
                    candidate.lstat()
                    is_marker_present = True
                except OSError:
                    # Mark as not found when lstat fails
                    is_marker_present = False
            # Return the current directory as project root when a marker is found
            if is_marker_present:
                return current

        # Move to the parent directory for the next iteration
        parent = current.parent
        # Stop when the filesystem root is reached and no further ascent is possible
        if parent == current:
            # Reached the filesystem root; stop searching.
            break
        current = parent

    return None
