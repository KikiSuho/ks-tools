"""
Windows-specific platform data and behavior for scrutiny.

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
>>> from scrutiny.platforms.windows import get_pathext
>>> len(get_pathext()) > 0
True

"""

from __future__ import annotations

import os
import shutil
import subprocess
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
#          IDE DETECTION DATA            #
# ====================================== #

IDE_PROCESSES: frozenset[str] = frozenset(
    {
        # VS Code
        "code",
        "code.exe",
        # JetBrains
        "pycharm",
        "pycharm64.exe",
        "pycharm.exe",
        "idea",
        "idea64.exe",
        "idea.exe",
        "charm",
        # Terminal editors
        "vim",
        "nvim",
        "gvim",
        "emacs",
        # Sublime / Atom
        "subl",
        "sublime_text",
        "sublime_text.exe",
        "atom",
        "atom.exe",
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
#        EXECUTABLE DISCOVERY            #
# ====================================== #


def get_pathext() -> list[str]:
    """Return executable extensions from PATHEXT, defaulting to common Windows extensions."""
    return os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)


def get_extra_search_dirs(interpreter_dir: str) -> list[str]:
    """
    Return extra directories to search for executables.

    On Windows, the ``Scripts/`` sub-directory next to the interpreter
    is included so that conda / virtualenv tools are discovered even
    when the environment has not been fully activated.

    Parameters
    ----------
    interpreter_dir : str
        Directory containing the running Python interpreter.

    Returns
    -------
    list[str]
        Extra directory paths to prepend to PATH search.

    """
    scripts_dir = str(Path(interpreter_dir) / "Scripts")
    return [scripts_dir]


# ====================================== #
#        SUBPROCESS MANAGEMENT           #
# ====================================== #


def get_subprocess_creation_flags() -> int:
    """Return creation flags for subprocess calls on Windows."""
    return subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined, no-any-return]


def get_subprocess_preexec_fn() -> Optional[Callable[[], None]]:
    """Return pre-exec function for subprocess calls on Windows."""
    return None


# ====================================== #
#              FILESYSTEM                #
# ====================================== #

_WRITABLE_PERMISSIONS = 0o700


def _remove_readonly(
    _func: object,
    path: str,
    _exc_info: object,
) -> None:
    """Error handler for ``shutil.rmtree`` that clears the read-only bit."""
    Path(path).chmod(_WRITABLE_PERMISSIONS)
    Path(path).unlink()


def safe_rmtree(directory: Path) -> None:
    """
    Remove *directory* and all contents, handling read-only files.

    On Windows, some tools (e.g. mypy) create read-only cache files
    that ``shutil.rmtree`` cannot remove without first clearing the
    read-only attribute.

    Parameters
    ----------
    directory : Path
        Directory to remove.

    """
    shutil.rmtree(directory, onerror=_remove_readonly)


# ====================================== #
#         PROCESS MANAGEMENT             #
# ====================================== #


def terminate_process_tree(pid: int) -> None:
    """
    Terminate a process and all its children on Windows.

    Parameters
    ----------
    pid : int
        Process ID to terminate.

    """
    pid = int(pid)  # Validate before passing to subprocess
    subprocess.run(  # nosec B603, B607 -- pid is always int; no user string reaches this call
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        check=False,
        capture_output=True,
    )
