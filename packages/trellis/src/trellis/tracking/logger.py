"""
Per-run log file I/O for structure change tracking.

Write categorized change logs to timestamped per-run files.

Functions
---------
log_structure_changes : Write categorized changes to a per-run timestamped log file.

Examples
--------
>>> log_structure_changes("/nonexistent/dir", "")
''

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from trellis.core.io import atomic_write_text

# Timestamp format for log filenames: YYYYMMDD_HHMMSS.
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def log_structure_changes(
    logs_dir: str,
    content: str,
) -> str:
    """
    Write pre-formatted change content to a per-run timestamped log file.

    Parameters
    ----------
    logs_dir : str
        Directory where log files are stored.
    content : str
        Pre-formatted change summary text to write.

    Returns
    -------
    str
        Path to the created log file, or empty string if content is empty
        or the write fails.

    """
    # Skip writing when there is no content to log
    if not content:
        return ""

    now = datetime.now(tz=timezone.utc)
    timestamp = now.strftime(_TIMESTAMP_FORMAT)
    filename = f"trellis_{timestamp}.txt"
    log_path = str(Path(logs_dir) / filename)

    # Return the log path on successful write; fall back to empty string on failure
    if atomic_write_text(log_path, content + "\n"):
        return log_path

    return ""
