"""
Atomic file write utilities for structure persistence and logging.

Provide a shared atomic-write function with retry logic and direct-write
fallback for Windows/Dropbox environments where transient file locks
cause ``os.replace`` failures.

Constants
---------
RETRY_DELAY_SECONDS : Delay in seconds between atomic replace retry attempts.

Functions
---------
atomic_write_text : Write text to a file atomically with retry and fallback.

Examples
--------
>>> import tempfile, os
>>> path = os.path.join(tempfile.mkdtemp(), "test.txt")
>>> atomic_write_text(path, "hello")
True

"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)

RETRY_DELAY_SECONDS = 0.1


def atomic_write_text(output_path: str, content: str) -> bool:
    """
    Write text content to a file atomically with retry and fallback.

    Write to a temporary sibling file first, then replace the target
    via ``Path.replace()``. On failure (e.g. Windows file lock from
    Dropbox or antivirus), retry once after a short delay, then fall
    back to a direct (non-atomic) write. The ``.tmp`` file is always
    cleaned up.

    Parameters
    ----------
    output_path : str
        Path where the file will be saved.
    content : str
        Text content to write.

    Returns
    -------
    bool
        True if the write succeeded (atomic or fallback), False if
        all write attempts failed.

    """
    tmp_path = Path(output_path + ".tmp")

    # Write content to temporary file first; fall back to direct write if temp file creation fails
    try:
        with tmp_path.open("w", encoding="utf-8") as file:
            file.write(content)
    except OSError as tmp_write_failure:
        # Temp file creation failed; fall back to direct write immediately
        _log.debug("Failed to write temp file %s: %s", tmp_path, tmp_write_failure)
        return _write_direct(output_path, content)

    # Attempt atomic replace with one retry for transient locks.
    if _try_replace(tmp_path, output_path):
        return True

    time.sleep(RETRY_DELAY_SECONDS)

    # Retry once after a short delay to handle transient file locks
    if _try_replace(tmp_path, output_path):
        return True

    # Both replace attempts failed; fall back to direct write.
    _cleanup_tmp(tmp_path)
    return _write_direct(output_path, content)


def _try_replace(tmp_path: Path, output_path: str) -> bool:
    """
    Attempt a single atomic replace operation.

    Parameters
    ----------
    tmp_path : Path
        Temporary file to replace from.
    output_path : str
        Target file path.

    Returns
    -------
    bool
        True if the replace succeeded.

    """
    # Attempt the atomic rename; return False on any OS-level failure
    try:
        tmp_path.replace(output_path)
        return True
    except OSError:
        # Replace failed due to file lock or permission issue
        return False


def _write_direct(output_path: str, content: str) -> bool:
    """
    Write content directly without atomic rename.

    Parameters
    ----------
    output_path : str
        Target file path.
    content : str
        Text content to write.

    Returns
    -------
    bool
        True if the direct write succeeded.

    """
    # Write directly to the target path without atomic rename
    try:
        with Path(output_path).open("w", encoding="utf-8") as file:
            file.write(content)
        return True
    except OSError as direct_write_failure:
        # All write strategies exhausted; report failure
        _log.debug("Direct write fallback failed for %s: %s", output_path, direct_write_failure)
        return False


def _cleanup_tmp(tmp_path: Path) -> None:
    """Remove a temporary file if it exists."""
    with contextlib.suppress(OSError):
        tmp_path.unlink(missing_ok=True)
