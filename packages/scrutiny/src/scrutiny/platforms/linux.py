"""
Linux-specific platform data and behavior for scrutiny.

Constants
---------
IDE_ENV_VARS : Environment variable names indicating IDE execution.
IDE_PROCESSES : Process names indicating IDE execution.

Functions
---------
get_extra_search_dirs : Return extra directories to search for executables.
get_pathext : Return executable file extensions for the platform.
get_subprocess_creation_flags : Return platform creation flags for subprocess.
get_subprocess_preexec_fn : Return pre-exec function for subprocess calls.
safe_rmtree : Remove a directory tree with platform-specific handling.
terminate_process_tree : Terminate a process and all its children.

Examples
--------
>>> from scrutiny.platforms.linux import get_pathext
>>> get_pathext()
['']

"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Optional

__all__ = [
    "IDE_ENV_VARS",
    "IDE_PROCESSES",
    "get_extra_search_dirs",
    "get_pathext",
    "get_subprocess_creation_flags",
    "get_subprocess_preexec_fn",
    "safe_rmtree",
    "terminate_process_tree",
]

# ====================================== #
#           IDE DETECTION DATA           #
# ====================================== #

IDE_PROCESSES: frozenset[str] = frozenset(
    {
        # VS Code
        "code",
        # JetBrains
        "pycharm",
        "charm",
        "idea",
        # Terminal editors
        "vim",
        "nvim",
        "gvim",
        "emacs",
        # Sublime / Atom
        "subl",
        "sublime_text",
        "atom",
    },
)

IDE_ENV_VARS: frozenset[str] = frozenset(
    {
        # VS Code
        "VSCODE_INJECTION",
        "VSCODE_PID",
        "VSCODE_IPC_HOOK_CLI",
        "VSCODE_GIT_IPC_HANDLE",
        # JetBrains
        "PYCHARM_HOSTED",
        "PYCHARM_DISPLAY_PORT",
        "JETBRAINS_IDE",
        "INTELLIJ_ENVIRONMENT_READER",
        "IDEA_INITIAL_DIRECTORY",
        "TERMINAL_EMULATOR",
        # Terminal editors
        "EMACS",
        "VIM",
        "NVIM",
        "NVIM_LISTEN_ADDRESS",
        "INSIDE_EMACS",
        # Other
        "SUBLIME_TEXT",
        "ATOM_HOME",
    },
)


# ====================================== #
#          EXECUTABLE DISCOVERY          #
# ====================================== #


def get_pathext() -> list[str]:
    """Return executable extensions for Linux (no extensions needed)."""
    return [""]


def get_extra_search_dirs(_interpreter_dir: str) -> list[str]:
    """
    Return extra directories to search for executables.

    On Linux, no extra directories are needed; ``bin/`` is already
    the standard location and is typically on PATH.

    Parameters
    ----------
    _interpreter_dir : str
        Directory containing the running Python interpreter (unused on Linux).

    Returns
    -------
    list[str]
        Empty list (no extra dirs on Linux).

    """
    return []


# ====================================== #
#         SUBPROCESS MANAGEMENT          #
# ====================================== #


_NO_CREATION_FLAGS = 0


def get_subprocess_creation_flags() -> int:
    """Return creation flags for subprocess calls on Linux."""
    return _NO_CREATION_FLAGS


def get_subprocess_preexec_fn() -> Optional[Callable[[], None]]:
    """
    Return pre-exec function for subprocess calls on Linux.

    Uses ``os.setsid`` to create a new session, enabling process-group
    termination via ``os.killpg``.

    Returns
    -------
    Optional[Callable[[], None]]
        ``os.setsid`` for session-based process group management.

    """
    return os.setsid


# ====================================== #
#              FILESYSTEM                #
# ====================================== #


def safe_rmtree(directory: Path) -> None:
    """
    Remove *directory* and all contents.

    On Linux, no special handling is needed; ``shutil.rmtree``
    works directly.

    Parameters
    ----------
    directory : Path
        Directory to remove.

    """
    shutil.rmtree(directory)


# ====================================== #
#          PROCESS MANAGEMENT            #
# ====================================== #


def terminate_process_tree(pid: int) -> None:
    """
    Terminate a process and all its children on Linux.

    Sends ``SIGTERM`` to the process group.  Falls back to killing
    just the single process if the group lookup fails.

    Parameters
    ----------
    pid : int
        Process ID to terminate.

    """
    pid = int(pid)  # Validate before passing to OS calls
    # Attempt group-level SIGTERM; fall back to single-process kill.
    try:
        # Send SIGTERM to the entire process group rooted at *pid*.
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # Group lookup failed; try killing just the single process.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
