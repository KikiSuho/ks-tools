"""
Logging, formatting, header display, and result reporting.

Functions
---------
relative_display_path : Convert an absolute file path to a root-relative display string.

Examples
--------
>>> from pathlib import Path
>>> relative_display_path("/projects/tools/src/main.py", Path("/projects/tools"))
'src/main.py'

"""

from __future__ import annotations

from pathlib import Path


def relative_display_path(file_path: str, effective_root: Path) -> str:
    """
    Convert an absolute file path to a root-relative string for display.

    Parameters
    ----------
    file_path : str
        Absolute or relative file path from tool output.
    effective_root : Path
        Project root to strip from the path prefix.

    Returns
    -------
    str
        Root-relative POSIX path when the file is under *effective_root*,
        or the original path unchanged when it is not.

    """
    # Attempt root-relative conversion; fall back to the original path.
    try:
        # Strip the project root prefix and return a POSIX path
        return Path(file_path).relative_to(effective_root).as_posix()
    except ValueError:
        # File is not under effective_root; return the path unchanged
        return Path(file_path).as_posix()
