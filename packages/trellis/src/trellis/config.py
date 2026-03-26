"""
Configuration, CLI parsing, and filter settings for project structure scanning.

Centralizes all configuration settings, visibility argument parsing, and
the immutable filter settings container used across scanning, filtering,
and change detection modules.

Classes
-------
CallFlowMode : Enum controlling call flow display mode.
Config : Mutable configuration settings for directory scanning and output generation.
VisibilitySettings : Parsed visibility and feature settings from CLI arguments.
FilterSettings : Immutable snapshot of filtering-related configuration for thread-safe use.

Functions
---------
build_tr_meta : Build the compact tr_meta string encoding current settings.
build_filter_settings : Create a FilterSettings snapshot from the current Config state.
parse_visibility_args : Parse CLI flags for visibility and feature settings.

Examples
--------
>>> settings = build_filter_settings(enable_ignore_dirs=False)
>>> settings.enable_ignore_dirs
False

>>> meta = build_tr_meta(show_types=True, show_decorators=False)
>>> "T1" in meta and "@0" in meta
True

"""

from __future__ import annotations

import warnings
from enum import Enum
from typing import ClassVar, NamedTuple, Optional, TypeVar

_T = TypeVar("_T")


def _or_default(override: Optional[_T], default: _T) -> _T:
    """Return *override* when not None, otherwise *default*."""
    return default if override is None else override


# ====================================== #
#          CONFIGURATION TYPES           #
# ====================================== #


class CallFlowMode(Enum):
    """
    Call flow display mode for orchestration-style functions.

    Attributes
    ----------
    OFF : str
        No call flow display.
    RAW : str
        Show all direct lexical calls with no filtering.
    SMART : str
        Score calls and show only the highest-signal orchestration calls.

    """

    OFF = "off"
    RAW = "raw"
    SMART = "smart"


class Config:
    """
    Configuration settings for the directory structure generator.

    This class centralizes all configuration settings used for scanning project
    directories, controlling what's shown in the structure visualization, and
    determining how changes are tracked and logged.

    Attributes
    ----------
    SHOW_PARAMS : bool
        Whether to include function parameters in the output.
        Default is True.
    SHOW_PRIVATE : bool
        Whether to include private methods (starting with '_') in the output.
        Default is False.
    SHOW_MANGLED : bool
        Whether to include name-mangled methods (starting with '__' but not
        ending with '__') in the output. Default is False.
    SHOW_DUNDER : bool
        Whether to include special/dunder methods (like '__init__') in the output.
        Default is False.
    SHOW_DOCS : bool
        Whether to show documentation files in the structure. Default is True.
    SHOW_TYPES : bool
        Whether to include type annotations on function parameters in the
        output. Default is True.
    SHOW_DECORATORS : bool
        Whether to show decorators on functions and classes. Decorators are
        rendered as parent nodes with the definition as a child. Default is
        True.
    MAX_LINE_WIDTH : int
        Target maximum output line width for call flow truncation and
        change summary formatting. Default is 100.
    CALL_FLOW_MODE : CallFlowMode
        Call flow display mode for orchestration-style functions.
        ``OFF`` disables display, ``RAW`` shows all direct calls,
        ``SMART`` scores and filters for high-signal calls.
        Default is ``CallFlowMode.SMART``.
    LOG_STRUCTURE_CHANGES : bool
        Whether to track and log changes between structure versions.
        Default is True.
    LOG_CONFIG_ONLY_CHANGES : bool
        Whether to ignore changes due to configuration settings. When False,
        only actual project structure changes are logged. Default is False.
    ENABLE_IGNORE_DIRS : bool
        Whether to apply directory ignore patterns during scanning.
        Default is True.
    ENABLE_IGNORE_FILES : bool
        Whether to apply file ignore patterns during scanning. Default is True.
    OUTPUT_DIR : str
        Directory where structure files are saved. Default is "docs".
    LOG_DIR : str
        Directory where change logs are stored. Default is "logs/trellis".
    DOC_EXTENSIONS : frozenset[str]
        Set of file extensions that are considered documentation files.
    IGNORE_DIRS : frozenset[str]
        User-configurable directories to exclude from scanning.
        Infrastructure noise lives in ``core.filters.HARD_IGNORE_DIRS``.
    IGNORE_FILES : frozenset[str]
        User-configurable files to exclude from scanning.
        Infrastructure noise lives in ``core.filters.HARD_IGNORE_FILES``.

    """

    # Default visibility settings
    SHOW_PARAMS = True
    SHOW_PRIVATE = False
    SHOW_MANGLED = False
    SHOW_DUNDER = False
    SHOW_DOCS = True
    SHOW_TYPES = True
    SHOW_DECORATORS = True

    # Output width
    MAX_LINE_WIDTH = 100

    # Call flow settings
    CALL_FLOW_MODE = CallFlowMode.SMART

    # Change detection settings
    LOG_STRUCTURE_CHANGES = True
    LOG_CONFIG_ONLY_CHANGES = False

    # Ignore list controls
    ENABLE_IGNORE_DIRS = True
    ENABLE_IGNORE_FILES = True

    # Output directories
    OUTPUT_DIR = "docs"
    LOG_DIR = "logs/trellis"

    # Documentation file extensions
    DOC_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {".md", ".txt", ".rst", ".org", ".adoc", ".wiki", ".rdoc"}
    )

    # Directories to exclude from scanning (user-configurable defaults). Infrastructure noise
    # (e.g. __pycache__, .git) lives in core.filters.HARD_IGNORE_DIRS and is always filtered.
    IGNORE_DIRS: ClassVar[frozenset[str]] = frozenset(
        {
            # IDE and editor directories
            ".idea",
            ".vscode",
            ".vs",
            ".atom",
            ".eclipse",
            ".junie",
            ".claude",
            # Virtual environments (generic names that may be project content)
            "env",
            ".env",
            # Build and distribution directories
            "build",
            "dist",
            # Documentation build output
            "_build",
            "site",
            "docs/build",
            "docs",
            # Temporary directories
            "tmp",
            "temp",
            ".direnv",
            "logs",
            "debug",
            "out",
            # CI/CD directories
            ".github",
            ".gitlab",
            ".circleci",
            # Testing
            "tests",
            # Tooling
            "scripts",
        }
    )

    # Files to exclude from scanning (user-configurable defaults). Infrastructure noise
    # (e.g. *.pyc, nul) lives in core.filters.HARD_IGNORE_FILES and is always filtered.
    IGNORE_FILES: ClassVar[frozenset[str]] = frozenset(
        {
            # Configuration files
            "*.yml",
            "*.toml",
            # GitHub-specific ignore patterns
            ".gitignore",
            ".gitattributes",
            # Test files
            "conftest.py",
            "*_test.py",
            "*_tests.py",
            "test_*.py",
            # Documentation files to ignore
            "LICENSE",
        }
    )


# ====================================== #
#           FILTER SETTINGS              #
# ====================================== #


class FilterSettings(NamedTuple):
    """
    Immutable snapshot of filtering-related configuration.

    Bundles the Config fields needed by filtering and change detection
    functions into a single immutable container with frozenset for
    collection fields.

    Attributes
    ----------
    enable_ignore_dirs : bool
        Whether directory ignore patterns are active.
    enable_ignore_files : bool
        Whether file ignore patterns are active.
    show_docs : bool
        Whether documentation files/directories are visible.
    doc_extensions : frozenset[str]
        File extensions considered documentation.
    output_dir : str
        Configured output directory name.
    ignore_dirs : frozenset[str]
        Directory patterns to exclude.
    ignore_files : frozenset[str]
        File patterns to exclude.
    log_dir : str
        Configured log directory name.
    log_structure_changes : bool
        Whether to track and log structure changes.
    log_config_only_changes : bool
        Whether to ignore changes due to configuration settings.

    """

    enable_ignore_dirs: bool
    enable_ignore_files: bool
    show_docs: bool
    doc_extensions: frozenset[str]
    output_dir: str
    ignore_dirs: frozenset[str]
    ignore_files: frozenset[str]
    log_dir: str
    log_structure_changes: bool
    log_config_only_changes: bool


def build_tr_meta(
    *,
    show_types: Optional[bool] = None,
    show_decorators: Optional[bool] = None,
    call_flow_mode: Optional[CallFlowMode] = None,
    show_docs: Optional[bool] = None,
    enable_ignore_dirs: Optional[bool] = None,
    enable_ignore_files: Optional[bool] = None,
    show_params: Optional[bool] = None,
    show_private: Optional[bool] = None,
    show_dunder: Optional[bool] = None,
    show_mangled: Optional[bool] = None,
) -> str:
    """
    Build the compact tr_meta string.

    The encoding covers all Config flags that affect tree output:

    - ``D`` SHOW_DOCS, ``I`` ENABLE_IGNORE_DIRS, ``F`` ENABLE_IGNORE_FILES
    - ``T`` SHOW_TYPES, ``@`` SHOW_DECORATORS, ``C`` (reserved, always 0)
    - ``P`` SHOW_PARAMS, ``V`` SHOW_PRIVATE, ``U`` SHOW_DUNDER
    - ``S`` SHOW_MANGLED, ``W`` CALL_FLOW_MODE (off/raw/smart)

    When a parameter is ``None`` (the default), the current ``Config``
    class attribute is read at call time. When an explicit value is
    passed, it takes precedence over ``Config``.

    Parameters
    ----------
    show_types : bool or None
        Whether type annotations are displayed.
    show_decorators : bool or None
        Whether decorators are displayed.
    call_flow_mode : CallFlowMode or None
        Call flow display mode.
    show_docs : bool or None
        Whether documentation files are shown.
    enable_ignore_dirs : bool or None
        Whether directory ignore patterns are active.
    enable_ignore_files : bool or None
        Whether file ignore patterns are active.
    show_params : bool or None
        Whether function parameters are shown.
    show_private : bool or None
        Whether private members are shown.
    show_dunder : bool or None
        Whether dunder members are shown.
    show_mangled : bool or None
        Whether name-mangled members are shown.

    Returns
    -------
    str
        Compact metadata string encoding current settings.

    """
    # Build and return the metadata string using Config defaults for None values
    return (
        f"D{int(_or_default(show_docs, Config.SHOW_DOCS))}"
        f"I{int(_or_default(enable_ignore_dirs, Config.ENABLE_IGNORE_DIRS))}"
        f"F{int(_or_default(enable_ignore_files, Config.ENABLE_IGNORE_FILES))}"
        f"T{int(_or_default(show_types, Config.SHOW_TYPES))}"
        f"@{int(_or_default(show_decorators, Config.SHOW_DECORATORS))}"
        f"C0"
        f"P{int(_or_default(show_params, Config.SHOW_PARAMS))}"
        f"V{int(_or_default(show_private, Config.SHOW_PRIVATE))}"
        f"U{int(_or_default(show_dunder, Config.SHOW_DUNDER))}"
        f"S{int(_or_default(show_mangled, Config.SHOW_MANGLED))}"
        f"W{_or_default(call_flow_mode, Config.CALL_FLOW_MODE).value}"
    )


def build_filter_settings(
    *,
    enable_ignore_dirs: Optional[bool] = None,
    enable_ignore_files: Optional[bool] = None,
    show_docs: Optional[bool] = None,
    doc_extensions: Optional[frozenset[str]] = None,
    output_dir: Optional[str] = None,
    ignore_dirs: Optional[frozenset[str]] = None,
    ignore_files: Optional[frozenset[str]] = None,
    log_dir: Optional[str] = None,
    log_structure_changes: Optional[bool] = None,
    log_config_only_changes: Optional[bool] = None,
) -> FilterSettings:
    """
    Create a FilterSettings snapshot.

    When a parameter is ``None`` (the default), the current ``Config``
    class attribute is read at call time.

    Parameters
    ----------
    enable_ignore_dirs : bool or None
        Whether directory ignore patterns are active.
    enable_ignore_files : bool or None
        Whether file ignore patterns are active.
    show_docs : bool or None
        Whether documentation files are visible.
    doc_extensions : frozenset[str] or None
        File extensions considered documentation.
    output_dir : str or None
        Configured output directory name.
    ignore_dirs : frozenset[str] or None
        Directory patterns to exclude.
    ignore_files : frozenset[str] or None
        File patterns to exclude.
    log_dir : str or None
        Configured log directory name.
    log_structure_changes : bool or None
        Whether to track and log structure changes.
    log_config_only_changes : bool or None
        Whether to ignore changes due to configuration settings.

    Returns
    -------
    FilterSettings
        Immutable snapshot of filtering-related configuration values.

    """
    return FilterSettings(
        enable_ignore_dirs=_or_default(enable_ignore_dirs, Config.ENABLE_IGNORE_DIRS),
        enable_ignore_files=_or_default(enable_ignore_files, Config.ENABLE_IGNORE_FILES),
        show_docs=_or_default(show_docs, Config.SHOW_DOCS),
        doc_extensions=frozenset(_or_default(doc_extensions, Config.DOC_EXTENSIONS)),
        output_dir=_or_default(output_dir, Config.OUTPUT_DIR),
        ignore_dirs=frozenset(_or_default(ignore_dirs, Config.IGNORE_DIRS)),
        ignore_files=frozenset(_or_default(ignore_files, Config.IGNORE_FILES)),
        log_dir=_or_default(log_dir, Config.LOG_DIR),
        log_structure_changes=_or_default(log_structure_changes, Config.LOG_STRUCTURE_CHANGES),
        log_config_only_changes=_or_default(
            log_config_only_changes, Config.LOG_CONFIG_ONLY_CHANGES
        ),
    )


# ====================================== #
#          VISIBILITY PARSING            #
# ====================================== #


class VisibilitySettings(NamedTuple):
    """
    Parsed visibility and feature settings from CLI arguments.

    Attributes
    ----------
    show_private : bool
        Whether to display private members.
    show_mangled : bool
        Whether to display name-mangled members.
    show_dunder : bool
        Whether to display dunder members.
    show_types : bool
        Whether to display type annotations.
    show_decorators : bool
        Whether to display decorators.
    call_flow_mode : CallFlowMode
        Call flow display mode for orchestration functions.

    """

    show_private: bool
    show_mangled: bool
    show_dunder: bool
    show_types: bool
    show_decorators: bool
    call_flow_mode: CallFlowMode


def _parse_call_flow_mode(argv: list[str]) -> CallFlowMode:
    """
    Parse the ``--call-flow`` option from raw CLI arguments.

    Parameters
    ----------
    argv : list[str]
        Command-line arguments to search.

    Returns
    -------
    CallFlowMode
        Parsed mode, or the Config default if not specified or invalid.

    """
    call_flow_mode = Config.CALL_FLOW_MODE
    # Scan for the --call-flow flag and consume its required value argument
    for index, arg in enumerate(argv):
        # Match the flag and ensure a value argument follows
        if arg == "--call-flow" and index + 1 < len(argv):
            mode_value = argv[index + 1].lower()
            # Attempt to resolve the mode value to a CallFlowMode enum member
            try:
                call_flow_mode = CallFlowMode(mode_value)
            except ValueError:
                # Warn on invalid mode so the user knows their input was ignored
                valid_modes = ", ".join(mode.value for mode in CallFlowMode)
                warnings.warn(
                    f"Unrecognized --call-flow value {mode_value!r}; "
                    f"valid options are: {valid_modes}. Using default.",
                    UserWarning,
                    stacklevel=2,
                )
    return call_flow_mode


def parse_visibility_args(
    argv: list[str],
) -> VisibilitySettings:
    """
    Parse CLI flags for visibility and feature settings.

    Bulk flags (``--show-all``, ``--hide-all``) set the baseline, then
    individual flags override specific settings. This means
    ``--show-all --hide-private`` shows everything except private members.

    Parameters
    ----------
    argv : list[str]
        Command-line arguments to parse.

    Returns
    -------
    VisibilitySettings
        Parsed visibility and feature settings.

    """
    # Start with Config defaults and convert argv to a set for fast lookups.
    args = set(argv)
    state: dict[str, bool] = {
        "show_private": Config.SHOW_PRIVATE,
        "show_mangled": Config.SHOW_MANGLED,
        "show_dunder": Config.SHOW_DUNDER,
        "show_types": Config.SHOW_TYPES,
        "show_decorators": Config.SHOW_DECORATORS,
    }

    # Parse --call-flow before visibility flags since bulk flags may adjust it.
    call_flow_mode = _parse_call_flow_mode(argv)

    # Apply bulk flags first to set the baseline; --hide-all wins if both present.
    has_show_all = "--show-all" in args
    has_hide_all = "--hide-all" in args
    # Enable all visibility options when --show-all is present without --hide-all
    if has_show_all and not has_hide_all:
        state["show_private"] = True
        state["show_mangled"] = True
        state["show_dunder"] = True
        # Upgrade call flow from OFF to SMART when showing everything
        if call_flow_mode == CallFlowMode.OFF:
            call_flow_mode = CallFlowMode.SMART
    # Apply --hide-all override, which takes precedence over --show-all
    if has_hide_all:
        state["show_private"] = False
        state["show_mangled"] = False
        state["show_dunder"] = False
        call_flow_mode = CallFlowMode.OFF

    # Map individual flags to their state key and value.
    flag_updates: dict[str, tuple[str, bool]] = {
        "--show-private": ("show_private", True),
        "--hide-private": ("show_private", False),
        "--show-mangled": ("show_mangled", True),
        "--hide-mangled": ("show_mangled", False),
        "--show-dunder": ("show_dunder", True),
        "--hide-dunder": ("show_dunder", False),
        "--show-types": ("show_types", True),
        "--hide-types": ("show_types", False),
        "--show-decorators": ("show_decorators", True),
        "--hide-decorators": ("show_decorators", False),
    }

    # Apply individual flags last so they override bulk flags
    for flag, (key, value) in flag_updates.items():
        # Update the state entry when the flag is present in arguments
        if flag in args:
            state[key] = value

    return VisibilitySettings(
        show_private=state["show_private"],
        show_mangled=state["show_mangled"],
        show_dunder=state["show_dunder"],
        show_types=state["show_types"],
        show_decorators=state["show_decorators"],
        call_flow_mode=call_flow_mode,
    )
